"""MCP Client — connects to MCP servers (stdio + HTTP/OAuth), wraps tools into NALLY's Tool class.

Stdio servers: per-call subprocess, no auth needed.
HTTP servers: OAuth2 flow, tokens stored in SQLite, reconnected per-call.
All MCP tools default to permission="write" (approval required) unless overridden.
"""
import asyncio
import logging
from typing import Any, Dict, List, Optional

from ..config import MCP_SERVERS, DATA_DIR
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
        config = self._server_config
        transport = config.get("transport", "stdio")

        if transport == "http":
            return await self._call_http(arguments)
        return await self._call_stdio(arguments)

    async def _call_stdio(self, arguments: dict) -> str:
        """Call via stdio transport (subprocess)."""
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        config = self._server_config
        server = StdioServerParameters(
            command=config["command"],
            args=config["args"],
            env=config.get("env"),
        )

        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(self.name.removeprefix(f"mcp_{config['name']}_"), arguments)
                return _extract_result(result)

    async def _call_http(self, arguments: dict) -> str:
        """Call via HTTP transport with stored token as Bearer header."""
        from nally.mcp.oauth import SQLiteTokenStorage
        import httpx, json

        config = self._server_config
        db = str(DATA_DIR / "nally.db")
        storage = SQLiteTokenStorage(db, config["name"])
        token = await storage.get_tokens()

        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if token:
            headers["Authorization"] = f"Bearer {token.access_token}"

        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": self.name.removeprefix(f"mcp_{config['name']}_"), "arguments": arguments},
        }

        async with httpx.AsyncClient() as client:
            resp = await client.post(config["url"], headers=headers, json=payload, timeout=30.0)
            result = _parse_sse_response(resp.text)
            if result and "result" in result:
                content = result["result"].get("content", [])
                parts = [b.get("text", "") for b in content if b.get("type") == "text"]
                return "\n".join(parts) if parts else "MCP tool returned no content"
            return f"MCP tool error: {result}"


def _extract_result(result) -> str:
    """Extract text content from an MCP tool result."""
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


def _parse_sse_response(text: str) -> dict | None:
    """Parse SSE-formatted MCP response into a dict."""
    import json
    for line in text.strip().split("\n"):
        if line.startswith("data: "):
            try:
                return json.loads(line[6:])
            except json.JSONDecodeError:
                continue
    # Try plain JSON
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        return None


def _wrap_mcp_schema(tool_info) -> dict:
    """Convert MCP tool's input_schema to NALLY's parameter format."""
    raw = getattr(tool_info, "inputSchema", None)
    if raw is None:
        raw = getattr(tool_info, "input_schema", None)
    schema = raw or {}
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

    Stdio servers: connects with timeout, fetches tools.
    HTTP servers: skipped at startup (tools registered after user connects).
    API key servers: skipped at startup (connected on-demand via connect_stdio_with_token).
    """
    if not MCP_SERVERS:
        return

    for server_config in MCP_SERVERS:
        name = server_config.get("name", "unknown")
        transport = server_config.get("transport", "stdio")
        permission = server_config.get("permission", "write")
        auth_mode = server_config.get("auth_mode", "")

        if transport == "http":
            logger.info(f"MCP server '{name}': HTTP transport, awaiting connection")
            continue

        if auth_mode == "api_key":
            logger.info(f"MCP server '{name}': API key auth, awaiting connection")
            continue

        try:
            _connect_stdio_server(reg, server_config, permission)
        except TimeoutError:
            logger.warning(f"MCP server '{name}': connection timed out, skipping")
        except Exception as e:
            logger.error(f"MCP server '{name}' failed to connect: {type(e).__name__}: {e}")


def _connect_stdio_server(reg, server_config: dict, default_permission: str):
    """Connect to a stdio MCP server, fetch tools, register them."""
    import concurrent.futures

    name = server_config.get("name", "unknown")

    async def _fetch_tools():
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client

        server = StdioServerParameters(
            command=server_config["command"],
            args=server_config["args"],
            env=server_config.get("env"),
        )

        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return result.tools

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        tools = pool.submit(
            asyncio.run, asyncio.wait_for(_fetch_tools(), timeout=30.0)
        ).result()
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


async def connect_http_server(server_config: dict, reg=None):
    """Connect to an HTTP MCP server after auth, fetch and register its tools."""
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    from nally.mcp.oauth import SQLiteTokenStorage

    name = server_config["name"]
    db = str(DATA_DIR / "nally.db")
    reg = reg or registry

    storage = SQLiteTokenStorage(db, name)
    token = await storage.get_tokens()

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token.access_token}"

    try:
        async with streamablehttp_client(server_config["url"], headers=headers) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                count = 0
                for tool_info in result.tools:
                    tool_name = f"mcp_{name}_{tool_info.name}"
                    params = _wrap_mcp_schema(tool_info)
                    mcp_tool = MCPTool(
                        name=tool_name,
                        description=tool_info.description or f"MCP tool: {tool_info.name}",
                        parameters=params,
                        server_config=server_config,
                        permission=server_config.get("permission", "write"),
                    )
                    reg.register(mcp_tool)
                    count += 1
                logger.info(f"MCP HTTP server '{name}': registered {count} tools")
                return count
    except Exception as e:
        logger.error(f"MCP HTTP server '{name}' failed: {type(e).__name__}: {e}")
        return 0


def connect_stdio_with_token(server_config: dict, reg=None) -> int:
    """Connect to a stdio MCP server that needs an env var token (e.g. Telegram).

    Reads the token from the env var specified in server_config['env_key'],
    passes it to the subprocess under server_config['env_name'] (or env_key),
    fetches and registers tools.
    Returns tool count, or 0 if env var is missing or connection fails.
    """
    import os
    name = server_config.get("name", "unknown")
    env_key = server_config.get("env_key", "")
    env_name = server_config.get("env_name", env_key)
    token_value = os.getenv(env_key, "")

    if not token_value:
        logger.info(f"MCP stdio '{name}': no {env_key} set, skipping")
        return 0

    env = {**os.environ, env_name: token_value}
    config_with_env = {**server_config, "env": env}

    try:
        _connect_stdio_server(reg or registry, config_with_env, server_config.get("permission", "write"))
        return len([t for t in (reg or registry).tools if t.name.startswith(f"mcp_{name}_")])
    except Exception as e:
        logger.error(f"MCP stdio '{name}' failed: {type(e).__name__}: {e}")
        return 0
