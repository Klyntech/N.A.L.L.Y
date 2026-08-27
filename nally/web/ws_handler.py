"""Nally WebSocket Handler — bidirectional real-time streaming.

Replaces SSE for the main chat flow. Lower latency, bidirectional,
better for multi-tab sync.

Protocol:
  Client -> Server:
    {"type": "user_message", "text": "hello", "tab_id": "tab_1"}
    {"type": "voice_audio", "audio": "<base64>", "tab_id": "tab_1"}
    {"type": "abort", "session_id": "web:default"}
    {"type": "approval", "tool_call_id": "...", "approved": true/false}

  Server -> Client:
    {"type": "thought", "text": "..."}
    {"type": "stream_chunk", "text": "..."}
    {"type": "tool_call", "name": "...", "args": {...}}
    {"type": "tool_result", "name": "...", "result": "..."}
    {"type": "confirmation_required", "tool_call_id": "...", "name": "..."}
    {"type": "response", "text": "final answer"}
    {"type": "voice_transcript", "text": "transcribed speech"}
    {"type": "tts_audio", "audio": "<base64 WAV>"}
    {"type": "error", "text": "..."}
    {"type": "done"}
"""

import asyncio
import base64
import hmac
import json
import logging
import os
import tempfile
import threading

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

    # Identity, not channel: whatever path the client used, all web sockets
    # share the owner's single brain session. The client-facing id is only a
    # route key; rooms register under the brain session so multi-tab sync,
    # plan events and aborts all target the shared brain.
    from ..agent.identity import resolve_session

    session_id = resolve_session("web").session_id

    cid = await ws_manager.connect(websocket, session_id)

    # Send initial connection confirmation so the client knows the WS is truly ready
    try:
        await ws_manager.send_json(cid, {"type": "connected", "session_id": session_id})
    except Exception:
        pass

    # Subscribe to event bus for plan events
    from ..events.bus import event_bus

    _loop = asyncio.get_running_loop()

    def _on_plan_event(event_type, data):
        """Broadcast plan events to this session's WebSocket clients."""
        try:
            asyncio.ensure_future(ws_manager.broadcast(session_id, {"type": event_type, **data}))
        except RuntimeError:
            _loop.call_soon_threadsafe(
                asyncio.ensure_future, ws_manager.broadcast(session_id, {"type": event_type, **data})
            )
        except Exception:
            pass

    unsubscribers = [
        event_bus.subscribe("plan_created", lambda e: _on_plan_event("plan_created", e.data)),
        event_bus.subscribe("plan_step_started", lambda e: _on_plan_event("plan_step_started", e.data)),
        event_bus.subscribe("plan_step_completed", lambda e: _on_plan_event("plan_step_completed", e.data)),
        event_bus.subscribe("plan_complete", lambda e: _on_plan_event("plan_complete", e.data)),
    ]

    try:
        # Heartbeat: ping every 30s to keep connection alive through Render proxy
        async def _heartbeat():
            while True:
                await asyncio.sleep(30)
                try:
                    await ws_manager.send_json(cid, {"type": "ping"})
                except Exception:
                    break

        heartbeat_task = asyncio.create_task(_heartbeat())

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
                asyncio.create_task(_process_message(cid, session_id, text, tab_id))

            # ── Abort ───────────────────────────────────
            elif msg_type == "abort":
                from ..core.abort import set_abort

                set_abort(session_id)
                await ws_manager.send_json(cid, {"type": "error", "text": "Operation aborted"})

            # ── Approval response ───────────────────────
            elif msg_type == "approval":
                tool_call_id = msg.get("tool_call_id", "")
                approved = msg.get("approved", False)
                from ..agent.graph import resolve_approval

                # resolve_approval does blocking SQLite I/O — keep it off the loop.
                await asyncio.to_thread(resolve_approval, tool_call_id, approved)
                await ws_manager.broadcast(
                    session_id,
                    {"type": "approval_resolved", "tool_call_id": tool_call_id, "approved": approved},
                )

            # ── Voice audio (from browser mic) ──────────
            elif msg_type == "voice_audio":
                audio_b64 = msg.get("audio", "")
                tab_id = msg.get("tab_id", "")
                audio_format = msg.get("format", "")
                if not audio_b64:
                    await ws_manager.send_json(cid, {"type": "error", "text": "No audio data"})
                    continue
                asyncio.create_task(_process_voice(cid, session_id, audio_b64, tab_id, audio_format))

            # ── Pong from client (heartbeat response) ──
            elif msg_type == "pong":
                pass  # just keeps the connection alive

            else:
                await ws_manager.send_json(cid, {"type": "error", "text": f"Unknown message type: {msg_type}"})

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        # Cancel heartbeat
        try:
            heartbeat_task.cancel()
        except Exception:
            pass
        # Unsubscribe from event bus
        for unsub in unsubscribers:
            try:
                unsub()
            except Exception:
                pass
        ws_manager.disconnect(cid, session_id)


async def _process_message(cid: str, session_id: str, text: str, tab_id: str):
    """Process a user message and stream events back."""
    from ..core.abort import check_abort, clear_abort

    # Intercept "call me" on web UI — redirect to Telegram
    if text.strip().lower() in ("call me", "call nally"):
        from ..config import NALLY_VOICE_CALLS_ENABLED
        if NALLY_VOICE_CALLS_ENABLED:
            await ws_manager.send_json(cid, {
                "type": "response",
                "text": 'Voice calls only work on Telegram. Send me "call me" there and I\'ll set up a voice chat for you.',
            })
            return

    # Check if session is busy — queue the message
    if session_manager.is_busy(session_id):
        pos = session_manager.queue_message(session_id, text)
        if pos < 0:
            await ws_manager.send_json(cid, {"type": "error", "text": "Queue full — try again shortly."})
        else:
            await ws_manager.send_json(
                cid, {"type": "busy", "text": f"Queued (position {pos}). Processing after current task."}
            )
        return

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
            # Trigger background reflection on session end
            try:
                from ..memory.reflector import reflector

                agent = session_manager._sessions.get(session_id)
                if agent and len(agent.messages) > 4:
                    threading.Thread(
                        target=reflector.reflect_on_conversation,
                        args=(agent.messages, session_id),
                        daemon=True,
                    ).start()
            except Exception:
                pass

    # Clear abort flag
    clear_abort(session_id)

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
        if check_abort(session_id):
            clear_abort(session_id)
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


async def _process_voice(cid: str, session_id: str, audio_b64: str, tab_id: str, audio_format: str = ""):
    """Process voice audio from browser: STT -> agent -> TTS -> stream audio back."""
    from ..core.abort import check_abort, clear_abort

    loop = asyncio.get_event_loop()

    try:
        # Decode base64 audio to bytes
        audio_bytes = base64.b64decode(audio_b64)

        if audio_format == "pcm_s16le":
            # Client decoded to raw 16kHz mono int16 PCM — use directly
            pcm_bytes = audio_bytes
        else:
            # Browser sent raw webm — decode with ffmpeg
            with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as tmp_in:
                tmp_in.write(audio_bytes)
                tmp_in_path = tmp_in.name

            tmp_out_path = tmp_in_path.replace(".webm", ".pcm")

            try:
                from ..utils import ffmpeg_available

                if not ffmpeg_available():
                    await ws_manager.send_json(
                        cid,
                        {
                            "type": "error",
                            "text": "ffmpeg not installed — required for voice. Install: choco install ffmpeg",
                        },
                    )
                    return

                proc = await asyncio.create_subprocess_exec(
                    "ffmpeg",
                    "-y",
                    "-i",
                    tmp_in_path,
                    "-f",
                    "s16le",
                    "-acodec",
                    "pcm_s16le",
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    tmp_out_path,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                await proc.wait()

                if proc.returncode != 0:
                    await ws_manager.send_json(cid, {"type": "error", "text": "Audio decode failed"})
                    return

                with open(tmp_out_path, "rb") as f:
                    pcm_bytes = f.read()
            finally:
                for p in [tmp_in_path, tmp_out_path]:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

        if len(pcm_bytes) < 3200:  # < 0.1s at 16kHz
            await ws_manager.send_json(cid, {"type": "error", "text": "Audio too short"})
            return

        # STT
        import numpy as np

        audio_f32 = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0

        from ..voice.stt import transcribe

        text = await loop.run_in_executor(None, transcribe, audio_f32.tobytes())

        if not text.strip():
            await ws_manager.send_json(cid, {"type": "error", "text": "Could not understand audio"})
            return

        # Send transcript back
        await ws_manager.send_json(cid, {"type": "voice_transcript", "text": text})

        # Process through agent
        queue: asyncio.Queue = asyncio.Queue()

        def stream_event(event, payload):
            try:
                flat = {"type": event}
                flat.update(payload)
                loop.call_soon_threadsafe(queue.put_nowait, flat)
            except Exception:
                pass

        def run_agent():
            try:
                response = session_manager.process(session_id, text, emit=stream_event)
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "response", "text": response})
            except NallyError as e:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "text": e.to_llm_format()})
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "text": str(e)})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        clear_abort(session_id)
        asyncio.ensure_future(loop.run_in_executor(None, run_agent))

        # Stream events back, capture final response
        final_response = ""
        while True:
            if check_abort(session_id):
                clear_abort(session_id)
                await ws_manager.send_json(cid, {"type": "error", "text": "Operation aborted by user."})
                await ws_manager.send_json(cid, {"type": "done"})
                return

            item = await queue.get()
            if item is None:
                break

            await ws_manager.send_json(cid, item)

            if item.get("type") == "response":
                final_response = item.get("text", "")

            # Broadcast to other tabs
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

        # TTS the response with voice summary
        if final_response:
            from ..voice.formatter import VoiceFormatter, VoiceMode
            from ..voice.tts import synthesize_to_wav

            # Generate voice summary via lightweight LLM
            voice_summary = await _generate_ws_voice_summary(final_response)

            # Format for speech
            formatter = VoiceFormatter()
            speak_text = formatter.format(final_response, mode=VoiceMode.SMART, summary=voice_summary)

            wav_bytes = await loop.run_in_executor(None, synthesize_to_wav, speak_text)
            if wav_bytes:
                wav_b64 = base64.b64encode(wav_bytes).decode("ascii")
                await ws_manager.send_json(cid, {"type": "tts_audio", "audio": wav_b64})

        await ws_manager.send_json(cid, {"type": "done"})

    except Exception as e:
        logger.error(f"Voice processing failed: {e}", exc_info=True)
        await ws_manager.send_json(cid, {"type": "error", "text": f"Voice processing failed: {e}"})


async def _generate_ws_voice_summary(text: str) -> str:
    """Generate a 1-2 sentence voice summary using the main LLM."""
    import re

    try:
        if len(text) <= 200:
            return text

        from ..agent.llm import llm

        summary_response = await asyncio.to_thread(
            llm.simple_chat,
            user_message=f"Rewrite this as a 1-2 sentence spoken summary. Keep it conversational and natural, like you're talking to a friend. No markdown, no lists, just flowing speech:\n\n{text}",
            system_prompt="You are a voice assistant. Rewrite responses for natural spoken delivery. Be conversational, warm, concise. Never use markdown, bullet points, or lists. Just flowing sentences.",
        )
        return summary_response.strip()
    except Exception as e:
        logger.warning(f"Voice summary generation failed: {e}")
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        if len(sentences) >= 2:
            return " ".join(sentences[:2])
        elif sentences:
            return sentences[0]
        return text[:200]
