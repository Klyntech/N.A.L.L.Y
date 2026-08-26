"""NallyBridge WebSocket handler — manages connected bridge devices.

Bridges connect via /ws/bridge/{device_id}?token=...
They register themselves and then receive tool execution requests.
"""

import asyncio
import json
import logging
import os
import time
import uuid
from typing import Optional

from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger("nally.bridge")

NALLY_BRIDGE_TOKEN = os.environ.get("NALLY_BRIDGE_TOKEN", "")


class BridgeDevice:
    """Represents a connected bridge device."""

    def __init__(self, device_id: str, websocket: WebSocket, platform: str, tools: list[str]):
        self.device_id = device_id
        self.websocket = websocket
        self.platform = platform
        self.tools = tools
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
        self._pending: dict[str, asyncio.Future] = {}  # request_id -> Future

    @property
    def devices(self) -> dict[str, BridgeDevice]:
        return self._devices

    def register(self, device_id: str, ws: WebSocket, platform: str, tools: list[str]) -> BridgeDevice:
        """Register a bridge device."""
        device = BridgeDevice(device_id, ws, platform, tools)
        self._devices[device_id] = device
        logger.info(f"Bridge registered: {device_id} (platform={platform}, tools={tools})")
        return device

    def unregister(self, device_id: str):
        """Remove a bridge device."""
        self._devices.pop(device_id, None)
        # Cancel any pending requests for this device
        for rid, fut in list(self._pending.items()):
            if not fut.done():
                fut.cancel()
                self._pending.pop(rid, None)
        logger.info(f"Bridge unregistered: {device_id}")

    def get_device(self, device_id: str) -> Optional[BridgeDevice]:
        """Get a specific bridge device."""
        return self._devices.get(device_id)

    def find_device_for_tool(self, tool: str) -> Optional[BridgeDevice]:
        """Find a connected bridge that supports the given tool."""
        for device in self._devices.values():
            if tool in device.tools:
                return device
        return None

    async def send_tool_request(
        self, device_id: str, tool: str, args: dict, timeout: float = 60.0
    ) -> tuple[str, bool]:
        """Send a tool request to a bridge and wait for the result.

        Returns (result, success).
        """
        device = self._devices.get(device_id)
        if not device:
            return f"Error: Bridge device not connected: {device_id}", False

        request_id = str(uuid.uuid4())[:12]
        future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future

        try:
            await device.websocket.send_json({
                "type": "tool_request",
                "request_id": request_id,
                "tool": tool,
                "args": args,
            })

            result = await asyncio.wait_for(future, timeout=timeout)
            return result

        except asyncio.TimeoutError:
            return f"Error: Bridge request timed out after {timeout}s", False
        except Exception as e:
            return f"Error communicating with bridge: {e}", False
        finally:
            self._pending.pop(request_id, None)

    def resolve_result(self, request_id: str, result: str, success: bool):
        """Resolve a pending tool request with its result."""
        future = self._pending.get(request_id)
        if future and not future.done():
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
    if not NALLY_BRIDGE_TOKEN or token != NALLY_BRIDGE_TOKEN:
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

                await websocket.send_json({
                    "type": "registered",
                    "session_id": f"bridge:{device_id}",
                    "device": device_id,
                })

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
            bridge_registry.unregister(device_id)
