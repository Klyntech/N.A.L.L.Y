"""MCP Client — connects to MCP servers (stdio + HTTP/OAuth), wraps tools into NALLY's Tool class.

Stdio servers: per-call subprocess, no auth needed.
HTTP servers: OAuth2 flow, tokens stored in SQLite, reconnected per-call.
All MCP tools default to permission="write" (approval required) unless overridden.
"""

import asyncio
import logging

from ..config import DATA_DIR, MCP_SERVERS
from ..tools.registry import Tool, registry

logger = logging.getLogger("nally.mcp")


class MCPTool(Tool):
    """Wrapper that turns an MCP tool schema into a NALLY Tool."""

    def __init__(self, name: str, description: str, parameters: dict, server_config: dict, permission: str = "write"):
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
        from mcp.client.stdio import stdio_client

        from mcp import ClientSession, StdioServerParameters

        config = self._server_config
        server = StdioServerParameters(
            command=config["command"],
            args=config["args"],
            env=config.get("env"),
        )

        try:
            async with stdio_client(server) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    tool_name = self.name.removeprefix(f"mcp_{config['name']}_").replace("_", "-")
                    result = await session.call_tool(tool_name, arguments)
                    return _extract_result(result)
        except ExceptionGroup as eg:
            # Unwrap the sub-exception from the TaskGroup
            for exc in eg.exceptions:
                return f"MCP tool error: {type(exc).__name__}: {exc}"
            return f"MCP tool error: {type(eg).__name__}: {eg}"
        except Exception as e:
            return f"MCP tool error: {type(e).__name__}: {e}"

    async def _call_http(self, arguments: dict) -> str:
        """Call via HTTP transport with stored token as Bearer header.

        Tries raw HTTP POST first, falls back to SSE client if that fails.
        """

        import httpx

        from nally.mcp.oauth import SQLiteTokenStorage

        config = self._server_config
        db = str(DATA_DIR / "nally.db")
        storage = SQLiteTokenStorage(db, config["name"])
        token = await storage.get_tokens()

        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
        if token:
            headers["Authorization"] = f"Bearer {token.access_token}"

        tool_name = self.name.removeprefix(f"mcp_{config['name']}_")
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": arguments},
        }

        # Try raw HTTP POST first (works for stateless Streamable HTTP servers)
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(config["url"], headers=headers, json=payload, timeout=30.0)
                result = _parse_sse_response(resp.text)
                if result and "result" in result:
                    content = result["result"].get("content", [])
                    parts = [b.get("text", "") for b in content if b.get("type") == "text"]
                    return "\n".join(parts) if parts else "MCP tool returned no content"
                # If we got an error response, try SSE fallback below
        except Exception as e:
            logger.debug(f"Raw HTTP POST failed for {config['name']}: {type(e).__name__}: {e}")

        # Fallback: use SSE client (for servers like Notion that need a session)
        try:
            from mcp.client.sse import sse_client

            from mcp import ClientSession

            sse_url = (
                config["url"].rstrip("/mcp") + "/sse" if config["url"].endswith("/mcp") else config["url"] + "/sse"
            )
            sse_headers = {}
            if token:
                sse_headers["Authorization"] = f"Bearer {token.access_token}"
            async with sse_client(sse_url, headers=sse_headers) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)
                    return _extract_result(result)
        except Exception as e:
            logger.debug(f"SSE fallback failed for {config['name']}: {type(e).__name__}: {e}")

        return f"MCP tool error: all transports failed for {config['name']}/{tool_name}"


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


def _wrap_mcp_schema_dict(schema: dict) -> dict:
    """Convert a raw inputSchema dict to NALLY's parameter format."""
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
    HTTP servers: tries reconnecting if tokens exist, otherwise awaits user connection.
    API key servers: tries reconnecting if env var set, otherwise awaits user connection.
    """
    if not MCP_SERVERS:
        return

    for server_config in MCP_SERVERS:
        name = server_config.get("name", "unknown")
        transport = server_config.get("transport", "stdio")
        permission = server_config.get("permission", "write")
        auth_mode = server_config.get("auth_mode", "")

        if transport == "http":
            # Try reconnecting if tokens already stored
            if _try_reconnect_http(server_config, reg):
                continue
            logger.info(f"MCP server '{name}': HTTP transport, awaiting connection")
            continue

        if auth_mode == "api_key":
            # Try reconnecting if env var is set
            if _try_reconnect_stdio_token(server_config, reg):
                continue
            logger.info(f"MCP server '{name}': API key auth, awaiting connection")
            continue

        try:
            _connect_stdio_server(reg, server_config, permission)
        except TimeoutError:
            logger.warning(f"MCP server '{name}': connection timed out, skipping")
        except Exception as e:
            logger.error(f"MCP server '{name}' failed to connect: {type(e).__name__}: {e}")


def _get_existing_tokens_sync(service: str, db_path: str):
    """Check if a service has stored tokens (synchronous, safe inside event loops)."""
    import sqlite3

    from mcp.shared.auth import OAuthToken

    from .oauth import _decrypt_token

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS mcp_oauth (
            service TEXT PRIMARY KEY,
            tokens TEXT,
            client_info TEXT,
            updated_at REAL
        )
    """)
    row = conn.execute("SELECT tokens FROM mcp_oauth WHERE service = ?", (service,)).fetchone()
    conn.close()
    if row is None or row["tokens"] is None:
        return None
    try:
        decrypted = _decrypt_token(row["tokens"])
        return OAuthToken.model_validate_json(decrypted)
    except Exception:
        return None


def _run_connect_http(server_config: dict, reg) -> int:
    """Run connect_http_server in a new event loop (safe for thread pools)."""
    import asyncio

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(connect_http_server(server_config, reg))
    finally:
        loop.close()
    name = server_config.get("name", "unknown")
    return len([t for t in (reg or registry).tools.values() if t.name.startswith(f"mcp_{name}_")])


def _try_reconnect_http(server_config: dict, reg) -> bool:
    """Try to reconnect to an HTTP MCP server if tokens exist. Returns True if tools loaded."""
    import concurrent.futures

    name = server_config.get("name", "unknown")
    db = str(DATA_DIR / "nally.db")

    # Check tokens synchronously to avoid asyncio.run() inside running event loop
    try:
        tokens = _get_existing_tokens_sync(name, db)
    except Exception:
        return False

    if not tokens:
        return False

    logger.info(f"MCP server '{name}': tokens found, reconnecting...")
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            count = pool.submit(_run_connect_http, server_config, reg).result(timeout=30)
        if count and count > 0:
            logger.info(f"MCP server '{name}': reconnected with {count} tools")
            return True
        else:
            logger.warning(f"MCP server '{name}': reconnect failed, awaiting manual connection")
            return False
    except Exception as e:
        logger.warning(f"MCP server '{name}': reconnect failed ({type(e).__name__}: {e})")
        return False


def _try_reconnect_stdio_token(server_config: dict, reg) -> bool:
    """Try to reconnect to a stdio MCP server if env var token is set. Returns True if tools loaded."""
    import os

    name = server_config.get("name", "unknown")
    env_key = server_config.get("env_key", "")
    if not env_key or not os.getenv(env_key):
        return False

    logger.info(f"MCP server '{name}': token found, reconnecting...")
    try:
        count = connect_stdio_with_token(server_config, reg)
        if count and count > 0:
            logger.info(f"MCP server '{name}': reconnected with {count} tools")
            return True
        return False
    except Exception as e:
        logger.warning(f"MCP server '{name}': reconnect failed ({type(e).__name__}: {e})")
        return False


def _connect_stdio_server(reg, server_config: dict, default_permission: str):
    """Connect to a stdio MCP server, fetch tools, register them."""
    import concurrent.futures
    import os

    name = server_config.get("name", "unknown")

    async def _fetch_tools():
        from mcp.client.stdio import stdio_client

        from mcp import ClientSession, StdioServerParameters

        env = dict(server_config.get("env") or {})
        auth_mode = server_config.get("auth_mode", "")
        if auth_mode == "api_key":
            env_key = server_config.get("env_key", "")
            if env_key and os.getenv(env_key):
                env[env_key] = os.getenv(env_key)

        server = StdioServerParameters(
            command=server_config["command"],
            args=server_config["args"],
            env=env if env else None,
        )

        async with stdio_client(server) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return result.tools

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        tools = pool.submit(asyncio.run, asyncio.wait_for(_fetch_tools(), timeout=30.0)).result(timeout=45)
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
    """Connect to an HTTP MCP server after auth, fetch and register its tools.

    Tries MCP SDK transports first, falls back to raw HTTP POST for stateless servers.
    """
    from mcp import ClientSession
    from nally.mcp.oauth import SQLiteTokenStorage

    name = server_config["name"]
    db = str(DATA_DIR / "nally.db")
    reg = reg or registry

    storage = SQLiteTokenStorage(db, name)
    token = await storage.get_tokens()

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token.access_token}"

    # Try Streamable HTTP first, fall back to SSE
    transport_errors = []
    for transport_name, connect_fn in _http_transport_fallback(server_config, headers):
        try:
            async with connect_fn() as (read, write, _):
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
                    logger.info(f"MCP HTTP server '{name}': registered {count} tools via {transport_name}")
                    return count
        except Exception as e:
            logger.debug(f"MCP HTTP server '{name}' {transport_name} failed: {type(e).__name__}: {e}")
            transport_errors.append(f"{transport_name}: {type(e).__name__}: {e}")
            continue

    # Fallback: raw HTTP POST for stateless servers (e.g. Google MCP)
    count = await _connect_http_stateless(server_config, headers, reg)
    if count:
        return count

    logger.error(f"MCP HTTP server '{name}' failed on all transports: {'; '.join(transport_errors)}")
    return 0


async def _connect_http_stateless(server_config: dict, headers: dict, reg) -> int:
    """Connect to stateless MCP servers via raw HTTP POST (no session init)."""
    import httpx

    name = server_config["name"]
    url = server_config["url"]
    h = {**headers, "Content-Type": "application/json", "Accept": "application/json, text/event-stream"}

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                url,
                headers=h,
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "tools/list",
                },
                timeout=15.0,
            )

        result = _parse_sse_response(resp.text)
        if not result or "result" not in result:
            logger.debug(f"Stateless HTTP tools/list failed for '{name}': {resp.text[:200]}")
            return 0

        tools = result["result"].get("tools", [])
        count = 0
        for tool_info in tools:
            tool_name = f"mcp_{name}_{tool_info['name']}"
            desc = tool_info.get("description", f"MCP tool: {tool_info['name']}")
            schema = tool_info.get("inputSchema", {"type": "object", "properties": {}})
            params = _wrap_mcp_schema_dict(schema)
            mcp_tool = MCPTool(
                name=tool_name,
                description=desc,
                parameters=params,
                server_config=server_config,
                permission=server_config.get("permission", "write"),
            )
            reg.register(mcp_tool)
            count += 1

        logger.info(f"MCP HTTP server '{name}': registered {count} tools via stateless-raw-http")
        return count
    except Exception as e:
        logger.debug(f"Stateless HTTP failed for '{name}': {type(e).__name__}: {e}")
        return 0


def _http_transport_fallback(server_config: dict, headers: dict):
    """Yield (transport_name, context_manager_factory) pairs for HTTP fallback."""
    from mcp.client.streamable_http import streamablehttp_client

    url = server_config["url"]

    # 1. Try Streamable HTTP at configured URL
    yield "streamable-http", lambda: streamablehttp_client(url, headers=headers)

    # 2. Try SSE at /sse endpoint (for servers like Notion that support both)
    try:
        from mcp.client.sse import sse_client

        sse_url = url.rstrip("/mcp") + "/sse" if url.endswith("/mcp") else url + "/sse"
        yield "sse", lambda: sse_client(sse_url, headers=headers)
    except ImportError:
        logger.debug("sse_client not available, skipping SSE fallback")


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
        return len([t for t in (reg or registry).tools.values() if t.name.startswith(f"mcp_{name}_")])
    except Exception as e:
        logger.error(f"MCP stdio '{name}' failed: {type(e).__name__}: {e}")
        return 0
