"""Nally WebSocket Handler — bidirectional real-time streaming.

Replaces SSE for the main chat flow. Lower latency, bidirectional,
better for multi-tab sync.

Protocol:
  Client -> Server:
    {"type": "user_message", "text": "hello", "tab_id": "tab_1"}
    {"type": "abort", "session_id": "web:default"}

  Server -> Client:
    {"type": "thought", "text": "..."}
    {"type": "stream_chunk", "text": "..."}
    {"type": "tool_call", "name": "...", "args": {...}}
    {"type": "tool_result", "name": "...", "result": "..."}
    {"type": "confirmation_required", "tool_call_id": "...", "name": "..."}
    {"type": "response", "text": "final answer"}
    {"type": "error", "text": "..."}
    {"type": "done"}
"""

import asyncio
import hmac
import json
import logging
import os
import time
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

from ..agent.sessions import session_manager
from ..core.errors import NallyError

logger = logging.getLogger("nally.ws")

# Read from env (same as app.py)
NALLY_ACCESS_TOKEN = os.environ.get("NALLY_ACCESS_TOKEN", "")


class ConnectionManager:
    """Manages WebSocket connections for multi-tab sync."""

    def __init__(self):
        self._connections: dict[str, WebSocket] = {}
        self._sessions: dict[str, set[str]] = {}  # session_id -> set of connection_ids
        self._counter = 0

    async def connect(self, websocket: WebSocket, session_id: str) -> str:
        """Accept and register a WebSocket connection."""
        await websocket.accept()
        self._counter += 1
        cid = f"ws_{self._counter}"
        self._connections[cid] = websocket

        if session_id not in self._sessions:
            self._sessions[session_id] = set()
        self._sessions[session_id].add(cid)

        logger.info(f"WebSocket connected: {cid} (session: {session_id}, total: {len(self._connections)})")
        return cid

    def disconnect(self, cid: str, session_id: str):
        """Remove a WebSocket connection."""
        self._connections.pop(cid, None)
        if session_id in self._sessions:
            self._sessions[session_id].discard(cid)
            if not self._sessions[session_id]:
                del self._sessions[session_id]
        logger.info(f"WebSocket disconnected: {cid} (total: {len(self._connections)})")

    async def send_json(self, cid: str, data: dict):
        """Send JSON to a specific connection."""
        ws = self._connections.get(cid)
        if ws:
            try:
                await ws.send_json(data)
            except Exception:
                self.disconnect(cid, "")

    async def broadcast(self, session_id: str, data: dict, exclude: str = ""):
        """Send JSON to all connections in a session (except excluded)."""
        cids = self._sessions.get(session_id, set()).copy()
        for cid in cids:
            if cid != exclude:
                await self.send_json(cid, data)

    async def broadcast_all(self, data: dict):
        """Send JSON to all connected clients."""
        for cid in list(self._connections.keys()):
            await self.send_json(cid, data)


# Singleton
ws_manager = ConnectionManager()


async def websocket_chat(websocket: WebSocket, session_id: str):
    """Handle a WebSocket chat connection.

    Protocol:
      1. Client connects to /ws/{session_id}?token=...
      2. Client sends user messages as JSON
      3. Server streams back events (thoughts, tool calls, response)
      4. Client can send abort to cancel
    """
    # Auth via query param
    token = websocket.query_params.get("token", "")
    if not NALLY_ACCESS_TOKEN or not hmac.compare_digest(token, NALLY_ACCESS_TOKEN):
        await websocket.close(code=4001, reason="Unauthorized")
        return

    cid = await ws_manager.connect(websocket, session_id)

    try:
        while True:
            # Receive message from client
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await ws_manager.send_json(cid, {"type": "error", "text": "Invalid JSON"})
                continue

            msg_type = msg.get("type", "")

            # ── User message ────────────────────────────
            if msg_type == "user_message":
                text = msg.get("text", "").strip()
                tab_id = msg.get("tab_id", "")

                if not text:
                    await ws_manager.send_json(cid, {"type": "error", "text": "Empty message"})
                    continue

                # Process in background
                asyncio.create_task(
                    _process_message(cid, session_id, text, tab_id)
                )

            # ── Abort ───────────────────────────────────
            elif msg_type == "abort":
                from ..web.app import _abort_flags

                _abort_flags[session_id] = True
                await ws_manager.send_json(cid, {"type": "error", "text": "Operation aborted"})

            # ── Approval response ───────────────────────
            elif msg_type == "approval":
                tool_call_id = msg.get("tool_call_id", "")
                approved = msg.get("approved", False)
                from ..agent.graph import resolve_approval

                resolve_approval(tool_call_id, approved)
                await ws_manager.broadcast(
                    session_id,
                    {"type": "approval_resolved", "tool_call_id": tool_call_id, "approved": approved},
                )

            else:
                await ws_manager.send_json(cid, {"type": "error", "text": f"Unknown message type: {msg_type}"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        ws_manager.disconnect(cid, session_id)


async def _process_message(cid: str, session_id: str, text: str, tab_id: str):
    """Process a user message and stream events back."""
    from ..web.app import _abort_flags, broadcast_manager

    queue: asyncio.Queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def stream_event(event, payload):
        """Callback for agent to emit events."""
        try:
            flat = {"type": event}
            flat.update(payload)
            loop.call_soon_threadsafe(queue.put_nowait, flat)
        except Exception:
            pass

    def run_agent():
        """Run agent in thread pool."""
        try:
            response = session_manager.process(session_id, text, emit=stream_event)
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "response", "text": response})
        except NallyError as e:
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "text": e.to_llm_format()})
        except Exception as e:
            loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "text": str(e)})
        finally:
            loop.call_soon_threadsafe(queue.put_nowait, None)

    # Clear abort flag
    _abort_flags.pop(session_id, None)

    # Broadcast user message to other tabs
    await ws_manager.broadcast(
        session_id,
        {"type": "user_message", "text": text, "tab_id": tab_id},
        exclude=cid,
    )

    # Start agent in background
    asyncio.ensure_future(loop.run_in_executor(None, run_agent))

    # Stream events back to client
    while True:
        # Check abort
        if _abort_flags.get(session_id):
            _abort_flags.pop(session_id, None)
            await ws_manager.send_json(cid, {"type": "error", "text": "Operation aborted by user."})
            await ws_manager.send_json(cid, {"type": "done"})
            return

        item = await queue.get()
        if item is None:
            break

        await ws_manager.send_json(cid, item)

        # Broadcast specific events to other tabs
        evt_type = item.get("type", "")
        if evt_type == "thought":
            await ws_manager.broadcast(
                session_id,
                {"type": "thinking", "text": item.get("text", ""), "tab_id": tab_id},
                exclude=cid,
            )
        elif evt_type == "response":
            await ws_manager.broadcast(
                session_id,
                {"type": "assistant_message", "text": item.get("text", ""), "tab_id": tab_id},
                exclude=cid,
            )

    await ws_manager.send_json(cid, {"type": "done"})
