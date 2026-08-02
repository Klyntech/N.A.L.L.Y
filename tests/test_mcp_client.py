"""Tests for MCP client: schema wrapping, permission defaults, no-op when empty."""

from unittest.mock import MagicMock, patch

from nally.mcp.client import MCPTool, _wrap_mcp_schema, connect_mcp_servers
from nally.tools.registry import ToolRegistry


def test_wrap_mcp_schema_basic():
    """MCP schema with required/optional params converts correctly."""
    fake_tool = MagicMock(spec=["inputSchema", "name", "description"])
    fake_tool.inputSchema = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"},
            "limit": {"type": "integer", "description": "Max results", "default": 10},
        },
        "required": ["query"],
    }

    params = _wrap_mcp_schema(fake_tool)
    assert "query" in params
    assert params["query"]["required"] is True
    assert params["query"]["type"] == "string"
    assert "limit" in params
    assert params["limit"]["required"] is False
    assert params["limit"]["default"] == 10


def test_wrap_mcp_schema_enum():
    """MCP schema with enum values preserves them."""
    fake_tool = MagicMock(spec=["inputSchema", "name", "description"])
    fake_tool.inputSchema = {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["read", "write", "delete"]},
        },
        "required": ["action"],
    }

    params = _wrap_mcp_schema(fake_tool)
    assert params["action"]["enum"] == ["read", "write", "delete"]


def test_wrap_mcp_schema_empty():
    """MCP schema with no properties returns empty dict."""
    fake_tool = MagicMock(spec=["inputSchema", "name", "description"])
    fake_tool.inputSchema = {"type": "object", "properties": {}}

    params = _wrap_mcp_schema(fake_tool)
    assert params == {}


def test_wrap_mcp_schema_none():
    """MCP tool with no schema returns empty dict."""
    fake_tool = MagicMock(spec=["inputSchema", "name", "description"])
    fake_tool.inputSchema = None

    params = _wrap_mcp_schema(fake_tool)
    assert params == {}


def test_mcp_tool_permission_default():
    """MCPTool defaults to permission='write'."""
    tool = MCPTool(
        name="mcp_fs_read_file",
        description="Read a file",
        parameters={},
        server_config={"name": "filesystem", "command": "npx", "args": []},
    )
    assert tool.permission == "write"


def test_mcp_tool_permission_custom():
    """MCPTool accepts custom permission."""
    tool = MCPTool(
        name="mcp_fs_read_file",
        description="Read a file",
        parameters={},
        server_config={"name": "filesystem", "command": "npx", "args": []},
        permission="safe",
    )
    assert tool.permission == "safe"


def test_connect_mcp_servers_empty():
    """connect_mcp_servers is a no-op when MCP_SERVERS is empty."""
    reg = ToolRegistry()
    with patch("nally.mcp.client.MCP_SERVERS", []):
        connect_mcp_servers(reg)
    assert len(reg.tools) == 0


def test_connect_mcp_servers_skips_non_stdio():
    """connect_mcp_servers skips servers with non-stdio transport."""
    reg = ToolRegistry()
    fake_server = [{"name": "remote", "transport": "http", "command": "x", "args": []}]
    with patch("nally.mcp.client.MCP_SERVERS", fake_server):
        connect_mcp_servers(reg)
    assert len(reg.tools) == 0


def test_connect_mcp_servers_error_handling():
    """connect_mcp_servers catches connection errors gracefully."""
    reg = ToolRegistry()
    fake_server = [
        {
            "name": "broken",
            "transport": "stdio",
            "command": "nonexistent_command",
            "args": [],
        }
    ]
    with patch("nally.mcp.client.MCP_SERVERS", fake_server):
        connect_mcp_servers(reg)  # should not raise
    assert len(reg.tools) == 0


# ── McpStatus Tool ──────────────────────────────────────


def test_mcp_status_tool_schema():
    """McpStatus tool has correct schema."""
    from nally.tools.mcp import McpStatus

    tool = McpStatus()
    assert tool.name == "mcp_status"
    assert tool.permission == "safe"
    schema = tool.to_openai_schema()
    assert schema["function"]["name"] == "mcp_status"


def test_mcp_status_lists_servers():
    """McpStatus returns output listing configured servers."""
    from nally.tools.mcp import McpStatus

    tool = McpStatus()

    fake_servers = [
        {
            "name": "fetch",
            "transport": "stdio",
            "command": "python",
            "args": [],
            "permission": "safe",
            "description": "Fetch",
        },
        {"name": "notion", "transport": "http", "auth_mode": "oauth", "permission": "write", "description": "Notion"},
    ]

    fake_registry = MagicMock()
    fake_registry.tools = {}

    with (
        patch("nally.config.MCP_SERVERS", fake_servers),
        patch("nally.mcp.client.registry", fake_registry),
        patch("nally.tools.mcp._check_status", return_value="Disconnected"),
    ):
        result = tool.execute()

    assert "2 configured" in result
    assert "fetch" in result
    assert "notion" in result
    assert "stdio" in result
    assert "http" in result


def test_mcp_status_connected_server():
    """McpStatus shows Connected when tools are registered."""
    from nally.tools.mcp import McpStatus

    tool = McpStatus()

    fake_servers = [
        {
            "name": "fetch",
            "transport": "stdio",
            "command": "python",
            "args": [],
            "permission": "safe",
            "description": "Fetch",
        },
    ]

    fake_registry = MagicMock()
    mock_tool = MagicMock()
    mock_tool.name = "mcp_fetch_fetch_page"
    fake_registry.tools = {"mcp_fetch_fetch_page": mock_tool}

    with patch("nally.config.MCP_SERVERS", fake_servers), patch("nally.mcp.client.registry", fake_registry):
        result = tool.execute()

    assert "1 connected" in result
    assert "Connected" in result
    assert "1 tool" in result
