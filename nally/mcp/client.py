"""MCP Client — connects to MCP servers, wraps their tools into NALLY's Tool class.

Each MCP-discovered tool gets permission="write" by default (requires approval).
Connections are per-call for stdio servers (subprocess lifecycle is simple).
"""
import asyncio
import json
import logging
from typing import Any, Dict, List, Optional

from ..config import MCP_SERVERS
from ..tools.registry import Tool, registry

logger = logging.getLogger("nally.mcp")


class MCPTool(Tool):
    """Wrapper that turns an MCP tool schema into a NALLY Tool."""

    def __init__(self, name: str, description: str, parameters: dict,
                 server_config: dict, permission: str = "write"):
        super().__init__(name, description, parameters, permission=permission)
        self._server_config = server_config

    def execute(self, **kwargs) -> str:
        """Call the MCP tool by spawning a fresh connection."""
        try:
            result = asyncio.run(self._call_mcp(kwargs))
            return result
        except Exception as e:
            return f"MCP tool error: {type(e).__name__}: {e}"

    async def _call_mcp(self, arguments: dict) -> str:
        """Async helper: connect to MCP server, call tool, return result."""
        from mcp import Client, StdioServerParameters
        from mcp.client.stdio import stdio_client

        config = self._server_config
        server = StdioServerParameters(
            command=config["command"],
            args=config["args"],
            env=config.get("env"),
        )

        async with Client(stdio_client(server)) as client:
            result = await client.call_tool(self.name, arguments)

            if result.is_error:
                error_text = ""
                for block in result.content:
                    if hasattr(block, "text"):
                        error_text += block.text
                return f"MCP tool failed: {error_text or 'unknown error'}"

            parts = []
            for block in result.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
            return "\n".join(parts) if parts else "MCP tool returned no content"


def _wrap_mcp_schema(tool_info) -> dict:
    """Convert MCP tool's input_schema to NALLY's parameter format."""
    schema = tool_info.input_schema or {}
    properties = schema.get("properties", {})
    required = set(schema.get("required", []))

    params = {}
    for name, prop in properties.items():
        params[name] = {
            "type": prop.get("type", "string"),
            "description": prop.get("description", ""),
            "required": name in required,
        }
        if "enum" in prop:
            params[name]["enum"] = prop["enum"]
        if "default" in prop:
            params[name]["default"] = prop["default"]

    return params


def connect_mcp_servers(reg):
    """Connect to all configured MCP servers and register their tools.

    Args:
        reg: ToolRegistry instance to register tools into.
    """
    if not MCP_SERVERS:
        return

    for server_config in MCP_SERVERS:
        name = server_config.get("name", "unknown")
        transport = server_config.get("transport", "stdio")
        permission = server_config.get("permission", "write")

        if transport != "stdio":
            logger.warning(f"MCP server '{name}': only stdio transport supported, skipping")
            continue

        try:
            _connect_stdio_server(reg, server_config, permission)
        except Exception as e:
            logger.error(f"MCP server '{name}' failed to connect: {type(e).__name__}: {e}")


def _connect_stdio_server(reg, server_config: dict, default_permission: str):
    """Connect to a stdio MCP server, fetch tools, register them."""
    name = server_config.get("name", "unknown")

    async def _fetch_tools():
        from mcp import Client, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server = StdioServerParameters(
            command=server_config["command"],
            args=server_config["args"],
            env=server_config.get("env"),
        )

        async with Client(stdio_client(server)) as client:
            result = await client.list_tools()
            return result.tools

    tools = asyncio.run(_fetch_tools())
    count = 0

    for tool_info in tools:
        tool_name = f"mcp_{name}_{tool_info.name}"
        params = _wrap_mcp_schema(tool_info)

        mcp_tool = MCPTool(
            name=tool_name,
            description=tool_info.description or f"MCP tool: {tool_info.name}",
            parameters=params,
            server_config=server_config,
            permission=default_permission,
        )
        reg.register(mcp_tool)
        count += 1

    logger.info(f"MCP server '{name}': registered {count} tools")
