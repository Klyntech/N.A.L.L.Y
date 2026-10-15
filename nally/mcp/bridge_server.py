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


def _allowed_hosts() -> list[str]:
    hosts = [host.strip() for host in os.getenv("NALLY_MCP_ALLOWED_HOSTS", "").split(",") if host.strip()]
    public_base_url = os.getenv("NALLY_BASE_URL", "").strip()
    public_host = urlparse(public_base_url).netloc
    if public_host:
        hosts.extend([public_host, f"{public_host}:*"])
    return list(dict.fromkeys(hosts + ["localhost:*", "127.0.0.1:*", "[::1]:*"]))


def _make_bridge_mcp() -> FastMCP:
    """Create FastMCP with transport security configured at construction time.

    MCP SDK 1.28–1.30: transport_security is a FastMCP constructor arg.
    streamable_http_app() takes no kwargs and reads settings.transport_security.
    """
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_allowed_hosts(),
        allowed_origins=[],
    )
    mcp = FastMCP("NallyBridge", transport_security=security)

    @mcp.tool()
    async def list_devices() -> str:
        """List connected NallyBridge devices and their supported tools."""
        from ..web.bridge_handler import bridge_registry

        devices = [device.to_dict() for device in bridge_registry.devices.values()]
        return json.dumps({"count": len(devices), "devices": devices}, ensure_ascii=False)

    @mcp.tool()
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

    return mcp


bridge_mcp = _make_bridge_mcp()


def build_bridge_mcp_app():
    """Build the authenticated Streamable HTTP ASGI app with Host validation."""
    # streamable_http_app() has no transport_security kwarg on mcp 1.30;
    # security is already set on the FastMCP instance above.
    protocol_app = bridge_mcp.streamable_http_app()
    return BearerAuthASGI(protocol_app)


def local_client_config() -> dict:
    """Build the local MCP-client config after the host server starts listening."""
    port = os.getenv("PORT", os.getenv("NALLY_PORT", "5000"))
    return {
        "name": "nalbridge",
        "url": f"http://127.0.0.1:{port}/mcp/nalbridge/mcp",
        "transport": "http",
        "auth_mode": "api_key",
        "env_key": "NALBRIDGE_MCP_TOKEN",
        "description": "NallyBridge remote device capabilities",
        "permission": "write",
    }
