"""Tests for the fixed tool registry and permission validation."""

import pytest

from nally.tools.registry import VALID_PERMISSIONS, Tool, ToolRegistry


def test_valid_permissions_set():
    assert {"safe", "destructive", "read_only", "write"} == VALID_PERMISSIONS


def test_register_valid_permission():
    registry = ToolRegistry()
    registry.register(Tool(name="test_tool", description="test", permission="safe"))
    assert registry.get("test_tool") is not None


def test_register_all_valid_permissions():
    registry = ToolRegistry()
    for permission in VALID_PERMISSIONS:
        registry.register(Tool(name=f"tool_{permission}", description="test", permission=permission))
    assert len(registry.get_all_tools()) == len(VALID_PERMISSIONS)


@pytest.mark.parametrize("permission", ["invalid", "admin", ""])
def test_register_invalid_permission_raises(permission):
    registry = ToolRegistry()
    with pytest.raises(ValueError, match="invalid permission"):
        registry.register(Tool(name="bad_tool", description="test", permission=permission))
    assert registry.get("bad_tool") is None


def test_get_all_tools_returns_registered_schemas():
    registry = ToolRegistry()
    registry.register(
        Tool(name="lookup", description="Search", parameters={"query": {"type": "string", "required": True}})
    )
    schemas = registry.get_all_tools()
    assert len(schemas) == 1
    assert schemas[0]["function"]["name"] == "lookup"
    assert schemas[0]["function"]["parameters"]["required"] == ["query"]
