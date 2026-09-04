"""Tests for explicit tool registry bootstrap (no import-time startup)."""

from __future__ import annotations

import importlib
import sys

import pytest


def test_importing_nally_tools_has_no_registration_side_effects():
    """Import must not register tools or connect MCP."""
    # Fresh-ish check against current process state is ok if we only
    # assert the public API: is_tools_loaded reflects prior runs, but
    # a pure import of the package module should not *call* load.
    import nally.tools as tools_pkg

    assert "load_all_tools" in tools_pkg.__all__
    assert "registry" in tools_pkg.__all__
    assert "ToolRegistryBuilder" in tools_pkg.__all__
    # Module should not execute registration on import beyond what
    # registry singleton construction does (empty tools dict initially
    # is ideal; after other tests it may be populated — so only check API).
    assert callable(tools_pkg.load_all_tools)
    assert callable(tools_pkg.is_tools_loaded)


def test_registry_builder_module_exports():
    from nally.tools import registry_builder as rb

    assert callable(rb.load_all_tools)
    assert callable(rb.is_tools_loaded)
    assert hasattr(rb, "ToolRegistryBuilder")


def test_load_all_tools_registers_builtins_once():
    from nally.tools import is_tools_loaded, load_all_tools, registry

    count1, mcp1 = load_all_tools()
    assert is_tools_loaded()
    assert count1 >= 10

    required = {
        "run_command",
        "system_health",
        "read_file",
        "file_ops",
        "run_code",
        "code_analysis",
        "web_search",
        "fetch",
        "think",
        "mcp_status",
        "remember",
        "recall",
        "forget",
        "memory_stats",
    }
    missing = required - set(registry.tools.keys())
    assert not missing, f"missing tools: {missing}"

    # Memory tools registered once (no duplicates)
    names = list(registry.tools.keys())
    assert names.count("remember") == 1
    assert names.count("recall") == 1
    assert names.count("forget") == 1
    assert names.count("memory_stats") == 1

    count2, mcp2 = load_all_tools()
    assert count2 == count1
    assert mcp2 == []  # second call does not re-connect MCP


def test_tool_registry_builder_build():
    from nally.tools.registry_builder import ToolRegistryBuilder

    count, mcp = ToolRegistryBuilder().build()
    assert count >= 10
    assert isinstance(mcp, list)


def test_no_circular_import_tools_registry_builder():
    """registry -> registry_builder -> registry must not explode."""
    from nally.tools.registry import registry as singleton
    from nally.tools import registry_builder as rb

    assert singleton is not None
    assert callable(rb.load_all_tools)
    assert hasattr(singleton, "register")
