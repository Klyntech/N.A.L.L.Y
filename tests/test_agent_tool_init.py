"""Regression tests for deterministic agent tool initialization."""

import importlib

import pytest

core = importlib.import_module("nally.agent.core")


def test_agent_loads_tools_before_snapshotting_schemas(monkeypatch):
    tools_module = importlib.import_module("nally.tools")
    registry_module = importlib.import_module("nally.tools.registry")
    events = []
    schemas = [{"type": "function", "function": {"name": "fetch"}}]

    monkeypatch.setattr(tools_module, "load_all_tools", lambda: events.append("load"))
    monkeypatch.setattr(registry_module.registry, "get_all_tools", lambda: events.append("snapshot") or schemas)

    assert core._get_tool_schemas() == schemas
    assert events == ["load", "snapshot"]


def test_agent_refuses_to_run_with_empty_tool_schema(monkeypatch):
    tools_module = importlib.import_module("nally.tools")
    registry_module = importlib.import_module("nally.tools.registry")
    monkeypatch.setattr(tools_module, "load_all_tools", lambda: None)
    monkeypatch.setattr(registry_module.registry, "get_all_tools", lambda: [])

    with pytest.raises(RuntimeError, match="without tools"):
        core._get_tool_schemas()
