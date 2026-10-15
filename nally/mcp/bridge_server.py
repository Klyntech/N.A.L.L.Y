"""Authenticated MCP server exposing connected NallyBridge devices.

The bridge WebSocket remains the device transport. This module makes the same
capabilities available to MCP clients over Streamable HTTP.
"""

import hmac
import json
import os
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

from ..tools.registry import Tool


bridge_mcp = FastMCP("NallyBridge")


def _authorized(scope) -> bool:
    expected = os.getenv("NALBRIDGE_MCP_TOKEN", "")
    if not expected:
        return False
    headers = dict(scope.get("headers", []))
    supplied = headers.get(b"authorization", b"").decode("latin-1")
    prefix, _, token = supplied.partition(" ")
    return prefix.lower() == "bearer" and bool(token) and hmac.compare_digest(token, expected)


class _BearerAuthASGI:
    """Require an explicit bearer secret before requests reach the MCP protocol."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] not in ("http", "websocket"):
            await self.app(scope, receive, send)
            return

        if not os.getenv("NALBRIDGE_MCP_TOKEN", ""):
            response = JSONResponse(
                {"error": "NallyBridge MCP is disabled: NALBRIDGE_MCP_TOKEN is not configured"},
                status_code=503,
            )
            await response(scope, receive, send)
            return

        if not _authorized(scope):
            response = JSONResponse({"error": "Unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return

        await self.app(scope, receive, send)


@bridge_mcp.tool()
async def list_devices() -> str:
    """List connected NallyBridge devices and their supported tools."""
    from ..web.bridge_handler import bridge_registry

    devices = [device.to_dict() for device in bridge_registry.devices.values()]
    return json.dumps({"count": len(devices), "devices": devices}, ensure_ascii=False)


@bridge_mcp.tool()
async def execute_device_tool(device: str, tool: str, arguments: dict | None = None) -> str:
    """Run an approved bridge capability on a connected device.

    Supported capabilities are run_command, file_io, and read_file as currently
    implemented by bridge clients. The bridge's shared token still authenticates
    each device connection.
    """
    if tool not in {"run_command", "file_ops", "read_file"}:
        return f"Error: unsupported NallyBridge capability: {tool}"

    from ..web.bridge_handler import bridge_registry

    target_id = device
    target = bridge_registry.get_device(device)
    if device == "any":
        target = bridge_registry.find_device_for_tool(tool)
        if not target:
            return "Error: no connected bridge device supports this capability"
        target_id = target.device_id
    elif not target:
        for device_id, candidate in bridge_registry.devices.items():
            if device_id.endswith(f":{device}") or device_id == device:
                target_id, target = device_id, candidate
                break

    if not target:
        return f"Error: NallyBridge device is not connected: {device}"
    if tool not in target.tools:
        return f"Error: device {target_id} does not support {tool}; available: {target.tools}"

    result, success = await bridge_registry.send_tool_request(target_id, tool, arguments or {})
    return json.dumps({"device": target_id, "tool": tool, "success": success, "result": result}, ensure_ascii=False)


def build_bridge_mcp_app():
    """Build an authenticated MCP ASGI app with an explicit host allowlist."""
    configured_hosts = [h.strip() for h in os.getenv("NALLY_MCP_ALLOWED_HOSTS", "").split(",") if h.strip()]
    public_base = os.getenv("NALLY_BASE_URL", "").strip()
    host = urlparse(public_base).netloc
    if host and host not in configured_hosts:
        configured_hosts.append(host)
    allowed_hosts = list(dict.fromkeys(configured_hosts + ["localhost:*", "127.0.0.1:*", "[::1]:*"]))
    protocol_app = bridge_mcp.streamable_http_app(
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=[],
        )
    )
    return _BearerAuthASGI(protocol_app)


class _BridgeMCPTool(Tool):
    """Expose the MCP bridge capabilities to Nally's local agent registry."""

    def __init__(self, name: str, description: str, parameters: dict):
        super().__init__(name=name, description=description, parameters=parameters, permission="write")

    def execute(self, **kwargs) -> str:
        import asyncio

        from ..web.bridge_handler import bridge_registry

        device = kwargs.get("device", "")
        target = bridge_registry.get_device(device)
        if device == "any":
            target = bridge_registry.find_device_for_tool(kwargs.get("tool", ""))
        if not target:
            return "Error: requested NallyBridge device is not connected"
        loop = target.loop
        if loop is None or not loop.is_running():
            return "Error: NallyBridge device event loop is unavailable"
        future = asyncio.run_coroutine_threadsafe(
            bridge_mcp_call(kwargs),
            loop,
        )
        try:
            return future.result(timeout=float(kwargs.get("timeout", 60)) + 5)
        except Exception as exc:
            future.cancel()
            return f"Error: NallyBridge MCP call failed: {type(exc).__name__}: {exc}"


async def bridge_mcp_call(arguments: dict) -> str:
    """Shared local-adapter execution path, dispatched on the bridge event loop."""
    device = arguments.get("device", "any")
    tool = arguments.get("tool", "")
    return await execute_device_tool(device=device, tool=tool, arguments=arguments.get("arguments", {}))


class _BridgeDevicesTool(Tool):
    def __init__(self):
        super().__init__(
            name="mcp_nalbridge_list_devices",
            description="List connected NallyBridge remote devices and their supported capabilities.",
            parameters={},
            permission="read_only",
        )

    def execute(self, **kwargs) -> str:
        from ..web.bridge_handler import bridge_registry

        devices = [device.to_dict() for device in bridge_registry.devices.values()]
        return json.dumps({"count": len(devices), "devices": devices}, ensure_ascii=False)


class _BridgeExecuteTool(Tool):
    def __init__(self):
        super().__init__(
            name="mcp_nalbridge_execute_device_tool",
            description="Execute run_command, file_ops, or read_file on a connected NallyBridge device. Requires an explicit device name or 'any'.",
            parameters={
                "device": {
                    "type": "string",
                    "required": True,
                    "description": "Connected device ID, device suffix, or 'any'.",
                },
                "tool": {
                    "type": "string",
                    "required": True,
                    "enum": ["run_command", "file_ops", "read_file"],
                    "description": "Capability implemented by the connected NallyBridge device.",
                },
                "arguments": {
                    "type": "object",
                    "description": "Arguments expected by the selected bridge capability.",
                },
            },
            permission="write",
        )

    def execute(self, device: str, tool: str, arguments=None, **kwargs) -> str:
        from ..web.bridge_handler import bridge_registry

        if tool not in {"run_command", "file_ops", "read_file"}:
            return f"Error: unsupported NallyBridge capability: {tool}"
        target = bridge_registry.get_device(device)
        if device == "any":
            target = bridge_registry.find_device_for_tool(tool)
        if not target:
            return "Error: requested NallyBridge device is not connected"
        target_id = target.device_id
        if tool not in target.tools:
            return f"Error: device {target_id} does not support {tool}; available: {target.tools}"

        import asyncio

        loop = target.loop
        if loop is None or not loop.is_running():
            return "Error: NallyBridge device event loop is unavailable"
        future = asyncio.run_coroutine_threadsafe(
            bridge_registry.send_tool_request(target_id, tool, arguments or {}),
            loop,
        )
        try:
            result, success = future.result(timeout=65)
            return json.dumps(
                {"device": target_id, "tool": tool, "success": success, "result": result},
                ensure_ascii=False,
            )
        except Exception as exc:
            future.cancel()
            return f"Error: NallyBridge request failed: {type(exc).__name__}: {exc}"


def register_local_tools(registry) -> None:
    """Register local in-process tools that mirror this server's MCP tools."""
    registry.register(_BridgeDevicesTool())
    registry.register(_BridgeExecuteTool())
