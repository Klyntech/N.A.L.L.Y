"""T3: dynamic refresh — MCP late registration propagates to filter + prompt."""

from unittest.mock import MagicMock

from nally.tools.manifest import get_capability_manifest, refresh_manifest
from nally.tools.registry import Tool


def _stubbed_agent(monkeypatch):
    import nally.agent.core as core_mod

    store = MagicMock()
    store.get_user_facts.return_value = "No user facts stored yet."
    store.get_conversation_summaries_text.return_value = ""
    store.get_recent_episodes_text.return_value = ""
    store.load_messages.return_value = []
    monkeypatch.setattr(core_mod, "memory_store", store)
    return core_mod


def test_refresh_propagates_late_mcp_tool(monkeypatch):
    from nally.agent.sessions import session_manager
    from nally.tools import load_all_tools
    from nally.tools.filter import tool_filter
    from nally.tools.registry import registry

    load_all_tools()
    tool_filter.build_index(registry.tools)

    _stubbed_agent(monkeypatch)
    # fresh session key to avoid cross-test pollution
    session_manager._sessions.pop("test-t3-refresh", None)
    session_manager._locks.pop("test-t3-refresh", None)
    agent = session_manager.get("test-t3-refresh", channel="web:default", route_key="web:default")

    assert "mcp_t3_probe_tool" not in agent.messages[0]["content"]
    assert "mcp_t3_probe_tool" not in get_capability_manifest()

    class FakeMCP(Tool):
        def __init__(self):
            super().__init__(name="mcp_t3_probe_tool", description="Fake MCP probe.", permission="safe")

        def execute(self, **kw):
            return "fake"

    registry.register(FakeMCP())
    try:
        # Before refresh, filter still stale
        sel_before = tool_filter.select("mcp_t3_probe_tool")
        assert not any(s["function"]["name"] == "mcp_t3_probe_tool" for s in sel_before)

        refresh_manifest()

        assert "mcp_t3_probe_tool" in get_capability_manifest()
        assert "mcp_t3_probe_tool" in agent.messages[0]["content"]
        sel_after = tool_filter.select("mcp_t3_probe_tool")
        assert any(s["function"]["name"] == "mcp_t3_probe_tool" for s in sel_after)
        # next turn would see it as callable (execution path still single registry)
        assert registry.get("mcp_t3_probe_tool") is not None
    finally:
        registry.tools.pop("mcp_t3_probe_tool", None)
        refresh_manifest()
        session_manager._sessions.pop("test-t3-refresh", None)
        session_manager._locks.pop("test-t3-refresh", None)


def test_no_phantom_when_mcp_unavailable():
    assert "mcp_never_tool_xyz" not in get_capability_manifest()
