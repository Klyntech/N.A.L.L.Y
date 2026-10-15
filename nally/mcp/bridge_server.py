"""Authenticated Streamable HTTP MCP server for NallyBridge.

The device protocol remains WebSocket-based. This server exposes connected
devices to MCP clients without retaining the old bridge_execute tool name.
"""

import hmac
import json
import os
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from starlette.responses import JSONResponse

bridge_mcp = FastMCP("NallyBridge")


def _bearer_matches(scope) -> bool:
    expected = os.getenv("NALBRIDGE_MCP_TOKEN", "")
    supplied = dict(scope.get("headers", [])).get(b"authorization", b"").decode("latin-1")
    scheme, _, token = supplied.partition(" ")
    return bool(expected and token and scheme.lower() == "bearer" and hmac.compare_digest(token, expected))


class BearerAuthASGI:
    """Authentication gate for the complete MCP HTTP mount."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        if not os.getenv("NALBRIDGE_MCP_TOKEN", ""):
            response = JSONResponse(
                {"error": "NallyBridge MCP is disabled because NALBRIDGE_MCP_TOKEN is not configured"},
                status_code=503,
            )
            await response(scope, receive, send)
            return
        if not _bearer_matches(scope):
            response = JSONResponse({"error": "Unauthorized"}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def _bridge_tool_name(tool: str) -> str:
    """Map the public, stable file_io name to the legacy device wire protocol."""
    return "file_ops" if tool == "file_io" else tool


@bridge_mcp.tool()
async def list_devices() -> str:
    """List connected NallyBridge devices and their supported tools."""
    from ..web.bridge_handler import bridge_registry

    devices = [device.to_dict() for device in bridge_registry.devices.values()]
    return json.dumps({"count": len(devices), "devices": devices}, ensure_ascii=False)


@bridge_mcp.tool()
async def execute_device_tool(device: str, tool: str, arguments: dict | None = None) -> str:
    """Execute run_command, file_io, or read_file on a connected device.

    Use an explicit device ID, a unique device suffix, or 'any'. Writes and
    shell execution require an authenticated MCP request and an authenticated
    NallyBridge device connection.
    """
    if tool not in {"run_command", "file_io", "read_file"}:
        return f"Error: unsupported NallyBridge capability: {tool}"

    from ..web.bridge_handler import bridge_registry

    wire_tool = _bridge_tool_name(tool)
    target_id = device
    target = bridge_registry.get_device(device)
    if device == "any":
        target = bridge_registry.find_device_for_tool(wire_tool)
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
    if wire_tool not in target.tools:
        return f"Error: device {target_id} does not support {tool}; available: {target.tools}"

    result, success = await bridge_registry.send_tool_request(target_id, wire_tool, arguments or {})
    return json.dumps(
        {"device": target_id, "tool": tool, "success": success, "result": result},
        ensure_ascii=False,
    )


def build_bridge_mcp_app():
    """Build the authenticated Streamable HTTP ASGI app with Host validation."""
    hosts = [host.strip() for host in os.getenv("NALLY_MCP_ALLOWED_HOSTS", "").split(",") if host.strip()]
    public_base_url = os.getenv("NALLY_BASE_URL", "").strip()
    public_host = urlparse(public_base_url).netloc
    if public_host and public_host not in hosts:
        hosts.append(public_host)
    allowed_hosts = list(dict.fromkeys(hosts + ["localhost:*", "127.0.0.1:*", "[::1]:*"]))
    protocol_app = bridge_mcp.streamable_http_app(
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=allowed_hosts,
            allowed_origins=[],
        )
    )
    return BearerAuthASGI(protocol_app)


class BridgeDevicesTool(Tool):
    """Local adapter for Nally to use the NallyBridge MCP capabilities."""

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


class BridgeExecuteTool(Tool):
    """Local agent adapter that routes MCP-equivalent requests to device transport."""

    def __init__(self):
        super().__init__(
            name="mcp_nalbridge_execute_device_tool",
            description=(
                "Execute run_command, file_io, or read_file on a connected NallyBridge device. "
                "Specify a device ID or 'any'. Requires a connected device."
            ),
            parameters={
                "device": {
                    "type": "string",
                    "required": True,
                    "description": "Connected device ID, device suffix, or 'any'.",
                },
                "tool": {
                    "type": "string",
                    "required": True,
                    "enum": ["run_command", "file_io", "read_file"],
                    "description": "Capability implemented by the selected device.",
                },
                "arguments": {
                    "type": "object",
                    "description": "Arguments for the selected capability.",
                },
            },
            permission="write",
        )

    def execute(self, device: str, tool: str, arguments=None, **kwargs) -> str:
        import asyncio

        from ..web.bridge_handler import bridge_registry

        if tool not in {"run_command", "file_io", "read_file"}:
            return f"Error: unsupported NallyBridge capability: {tool}"

        wire_tool = _bridge_tool_name(tool)
        target = bridge_registry.get_device(device)
        if device == "any":
            target = bridge_registry.find_device_for_tool(wire_tool)
        if not target:
            return "Error: requested NallyBridge device is not connected"
        if wire_tool not in target.tools:
            return f"Error: device {target.device_id} does not support {tool}; available: {target.tools}"

        loop = target.loop
        if loop is None or not loop.is_running():
            return "Error: NallyBridge device event loop is unavailable"
        try:
            future = asyncio.run_coroutine_threadsafe(
                bridge_registry.send_tool_request(target.device_id, wire_tool, arguments or {}),
                loop,
            )
            result, success = future.result(timeout=65)
            return json.dumps(
                {"device": target.device_id, "tool": tool, "success": success, "result": result},
                ensure_ascii=False,
            )
        except Exception as exc:
            return f"Error: NallyBridge request failed: {type(exc).__name__}: {exc}"


def register_local_tools(registry) -> None:
    """Register local wrappers that mirror the server's actual MCP tools."""
    registry.register(BridgeDevicesTool())
    registry.register(BridgeExecuteTool())
