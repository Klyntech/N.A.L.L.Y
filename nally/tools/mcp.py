"""MCP Status Tool — shows configured MCP servers and their connection status."""

import os

from .registry import Tool


class McpStatus(Tool):
    def __init__(self):
        super().__init__(
            name="mcp_status",
            description="List all configured MCP servers, their transport, auth mode, and connection status",
            permission="safe",
        )

    def execute(self, **kwargs) -> str:
        from ..config import DATA_DIR, MCP_SERVERS

        db = str(DATA_DIR / "nally.db")

        # Lazy import to avoid circular imports
        from ..mcp.client import registry as mcp_registry

        lines = []
        connected_count = 0

        for server in MCP_SERVERS:
            name = server["name"]
            transport = server.get("transport", "stdio")
            permission = server.get("permission", "safe")

            # Determine connection status
            status = _check_status(server, db, mcp_registry)
            if status.startswith("Connected"):
                connected_count += 1

            # Build tool count info
            tool_count = len([t for t in mcp_registry.tools.values() if t.name.startswith(f"mcp_{name}_")])
            tool_info = f" ({tool_count} tool{'s' if tool_count != 1 else ''})" if tool_count > 0 else ""

            lines.append(f"{name:<12} {transport:<6} {permission:<12} {status}{tool_info}")

        summary = f"MCP Servers ({len(MCP_SERVERS)} configured, {connected_count} connected):"
        return summary + "\n" + "\n".join(lines)


def _check_status(server: dict, db: str, mcp_registry) -> str:
    """Check connection status for a single MCP server."""
    name = server["name"]
    transport = server.get("transport", "stdio")
    auth_mode = server.get("auth_mode", "")

    # Check if tools are already registered
    registered = [t for t in mcp_registry.tools.values() if t.name.startswith(f"mcp_{name}_")]
    if registered:
        return "Connected"

    if transport == "http":
        if auth_mode == "oauth":
            # Check if tokens exist in DB
            try:
                import concurrent.futures
                import asyncio

                from ..mcp.oauth import get_existing_tokens

                async def _check():
                    return await get_existing_tokens(name, db)

                try:
                    loop = asyncio.get_running_loop()
                except RuntimeError:
                    loop = None

                if loop and loop.is_running():
                    with concurrent.futures.ThreadPoolExecutor() as pool:
                        tokens = pool.submit(asyncio.run, _check()).result()
                else:
                    tokens = asyncio.run(_check())

                if tokens:
                    return "Token stored (tools not loaded)"
                return "Disconnected"
            except Exception as e:
                logger.debug(f"MCP status check failed for {name}: {e}")
                return "Disconnected"
            except Exception:
                return "Disconnected"
        else:
            return "Disconnected"

    elif transport == "stdio":
        if auth_mode == "api_key":
            # Check if env var is set
            env_key = server.get("env_key", "")
            if env_key and os.getenv(env_key):
                return "Token set (not connected)"
            return f"Disconnected (no {env_key})"
        else:
            # Stdio without auth — check if command exists
            command = server.get("command", "")
            if command:
                return "Ready"
            return "Disconnected"

    return "Unknown"
