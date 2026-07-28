"""Tests for MCP client: schema wrapping, permission defaults, no-op when empty."""
import pytest
from unittest.mock import patch, MagicMock

from nally.tools.registry import ToolRegistry, Tool
from nally.mcp.client import _wrap_mcp_schema, MCPTool, connect_mcp_servers


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
    fake_server = [{
        "name": "broken",
        "transport": "stdio",
        "command": "nonexistent_command",
        "args": [],
    }]
    with patch("nally.mcp.client.MCP_SERVERS", fake_server):
        connect_mcp_servers(reg)  # should not raise
    assert len(reg.tools) == 0
