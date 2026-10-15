"""NallyBridge WebSocket handler — manages connected bridge devices.

Bridges connect via /ws/bridge/{device_id}?token=...
They register themselves and then receive tool execution requests.
"""

import asyncio
import hmac
import json
import logging
import os
import threading
import time
import uuid
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("nally.bridge")


class BridgeDevice:
    """Represents a connected bridge device."""

    def __init__(self, device_id: str, websocket: WebSocket, platform: str, tools: list[str]):
        self.device_id = device_id
        self.websocket = websocket
        self.platform = platform
        self.tools = tools
        self.loop = asyncio.get_running_loop()
        self.connected_at = time.time()
        self.last_pong = time.time()

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "platform": self.platform,
            "tools": self.tools,
            "connected_at": self.connected_at,
            "last_pong": self.last_pong,
        }


class BridgeRegistry:
    """Tracks all connected bridge devices and routes tool requests."""

    def __init__(self):
        self._devices: dict[str, BridgeDevice] = {}
        # request_id -> (device_id, Future); only the disconnected device's work is cancelled.
        self._pending: dict[str, tuple[str, asyncio.Future]] = {}
        self._lock = threading.RLock()

    @property
    def devices(self) -> dict[str, BridgeDevice]:
        """Return a snapshot so callers cannot mutate the live registry."""
        with self._lock:
            return dict(self._devices)

    def register(self, device_id: str, ws: WebSocket, platform: str, tools: list[str]) -> BridgeDevice:
        """Register a device and cancel requests still tied to a replaced connection."""
        device = BridgeDevice(device_id, ws, platform, tools)
        stale_futures = []
        with self._lock:
            previous = self._devices.get(device_id)
            self._devices[device_id] = device
            if previous and previous.websocket is not ws:
                stale = [
                    (rid, fut)
                    for rid, (target_id, fut) in self._pending.items()
                    if target_id == device_id
                ]
                stale_futures = [future for _, future in stale]
                for request_id, _ in stale:
                    self._pending.pop(request_id, None)

        for future in stale_futures:
            loop = future.get_loop()
            if not future.done() and loop.is_running():
                loop.call_soon_threadsafe(future.cancel)

        logger.info(f"Bridge registered: {device_id} (platform={platform}, tools={tools})")
        return device

    def unregister(self, device_id: str, websocket: WebSocket | None = None):
        """Remove the device only if this exact connection is still registered."""
        with self._lock:
            current = self._devices.get(device_id)
            if current is None or (websocket is not None and current.websocket is not websocket):
                return
            self._devices.pop(device_id, None)
            pending = [
                (rid, fut)
                for rid, (target_id, fut) in self._pending.items()
                if target_id == device_id
            ]
            for rid, _ in pending:
                self._pending.pop(rid, None)

        # Futures belong to each request's event loop; cancel them thread-safely.
        for _, fut in pending:
            loop = fut.get_loop()
            if not fut.done() and loop.is_running():
                loop.call_soon_threadsafe(fut.cancel)
        logger.info(f"Bridge unregistered: {device_id}")

    def get_device(self, device_id: str) -> Optional[BridgeDevice]:
        """Get a specific bridge device."""
        with self._lock:
            return self._devices.get(device_id)

    def find_device_for_tool(self, tool: str) -> Optional[BridgeDevice]:
        """Find a connected bridge that supports the given tool."""
        with self._lock:
            for device in self._devices.values():
                if tool in device.tools:
                    return device
        return None

    async def send_tool_request(self, device_id: str, tool: str, args: dict, timeout: float = 60.0) -> tuple[str, bool]:
        """Send a tool request to a bridge and wait for the result.

        Returns (result, success).
        """
        with self._lock:
            device = self._devices.get(device_id)
        if not device:
            return f"Error: Bridge device not connected: {device_id}", False
        if device.loop is not asyncio.get_running_loop():
            return f"Error: request must run on the bridge server event loop for {device_id}", False

        request_id = str(uuid.uuid4())
        future = asyncio.get_running_loop().create_future()
        with self._lock:
            self._pending[request_id] = (device_id, future)

        try:
            await device.websocket.send_json(
                {
                    "type": "tool_request",
                    "request_id": request_id,
                    "tool": tool,
                    "args": args,
                }
            )

            result = await asyncio.wait_for(future, timeout=timeout)
            return result

        except TimeoutError:
            return f"Error: Bridge request timed out after {timeout}s", False
        except Exception as e:
            return f"Error communicating with bridge: {e}", False
        finally:
            with self._lock:
                self._pending.pop(request_id, None)

    def resolve_result(self, request_id: str, result: str, success: bool):
        """Resolve a pending tool request with its result."""
        with self._lock:
            entry = self._pending.get(request_id)
        if entry:
            _, future = entry
            if not future.done():
                future.set_result((result, success))


# Singleton
bridge_registry = BridgeRegistry()


async def bridge_websocket(websocket: WebSocket, device_id: str):
    """Handle a WebSocket connection from a bridge device.

    Protocol:
      1. Bridge connects to /ws/bridge/{device_id}?token=...
      2. Bridge sends bridge_register
      3. NALLY sends registered confirmation
      4. NALLY sends tool_requests, bridge sends tool_results
      5. Heartbeat: ping/pong
    """
    # Auth via query param
    token = websocket.query_params.get("token", "")
    expected_token = os.getenv("NALLY_BRIDGE_TOKEN", "")
    if not expected_token or not hmac.compare_digest(token, expected_token):
        logger.warning(f"Bridge auth failed for device: {device_id}")
        await websocket.close(code=4001, reason="Unauthorized")
        return

    await websocket.accept()
    logger.info(f"Bridge WebSocket connected: {device_id}")

    device = None

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"type": "error", "text": "Invalid JSON"})
                continue

            msg_type = msg.get("type", "")

            if msg_type == "bridge_register":
                platform = msg.get("platform", "unknown")
                tools = msg.get("tools", [])
                device = bridge_registry.register(device_id, websocket, platform, tools)

                await websocket.send_json(
                    {
                        "type": "registered",
                        "session_id": f"bridge:{device_id}",
                        "device": device_id,
                    }
                )

            elif msg_type == "tool_result":
                request_id = msg.get("request_id", "")
                result = msg.get("result", "")
                success = msg.get("success", False)
                bridge_registry.resolve_result(request_id, result, success)

            elif msg_type == "pong":
                if device:
                    device.last_pong = time.time()

            elif msg_type == "error":
                logger.warning(f"Bridge error: {msg.get('text', 'unknown')}")

            else:
                logger.debug(f"Unknown bridge message: {msg_type}")

    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"Bridge WebSocket error: {e}")
    finally:
        if device:
            bridge_registry.unregister(device_id, websocket=websocket)
