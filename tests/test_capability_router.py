"""Tests for CapabilityRouter — Phase 5 routing boundary.

Acceptance conditions:
  1. resolve() returns RoutingDecision with correct schemas/available/denied
  2. suggest_fallback() returns correct alternative for known tools
  3. suggest_fallback() returns None when no alternative exists
  4. SubAgent tool selection goes through the router
  5. RoutingDecision is backward-compatible (iterable, len-able)
  6. Permission filtering works at resolve time
"""

from unittest.mock import MagicMock, patch

import pytest

from nally.tools.router_types import BUILTIN_ROUTES, CapabilityTag, RoutingDecision, ToolRoute
from nally.tools.capability_router import CapabilityRouter, capability_router
from nally.tools.registry import Tool, ToolRegistry


# ── Helper: minimal in-memory registry for testing ───────────


def _make_registry():
    """Build a small ToolRegistry with a handful of tools."""
    reg = ToolRegistry()

    reg.register(Tool("run_command", "Run a shell command", {"command": {"type": "string"}}, permission="safe"))
    reg.register(Tool("read_file", "Read a file", {"path": {"type": "string"}}, permission="safe"))
    reg.register(Tool("file_ops", "File operations", {"action": {"type": "string"}}, permission="safe"))
    reg.register(Tool("web_search", "Search the web", {"query": {"type": "string"}}, permission="safe"))
    reg.register(Tool("fetch", "Fetch a URL", {"url": {"type": "string"}}, permission="safe"))
    reg.register(Tool("memory", "Recall memories", {"query": {"type": "string"}}, permission="safe"))
    reg.register(Tool("agent", "Delegate to sub-agent", {"goal": {"type": "string"}}, permission="safe"))
    reg.register(Tool("think", "Structured reasoning", {"question": {"type": "string"}}, permission="safe"))
    return reg


def _make_router():
    """Build a fresh CapabilityRouter with the test registry."""
    return CapabilityRouter()


# ── 1. RoutingDecision data model ───────────────────────────


def test_routing_decision_iterable():
    """RoutingDecision is iterable (backward-compat with List[Dict] callers)."""
    d = RoutingDecision(
        schemas=[{"function": {"name": "a"}}, {"function": {"name": "b"}}],
        available={"a", "b"},
        denied=set(),
    )
    names = [s["function"]["name"] for s in d]
    assert names == ["a", "b"]


def test_routing_decision_len():
    """RoutingDecision has len()."""
    d = RoutingDecision(schemas=[{}, {}, {}], available=set(), denied=set())
    assert len(d) == 3


def test_routing_decision_bool():
    """RoutingDecision is truthy when non-empty, falsy when empty."""
    assert RoutingDecision(schemas=[{}], available=set(), denied=set())
    assert not RoutingDecision(schemas=[], available=set(), denied=set())


def test_routing_decision_fields():
    """RoutingDecision carries all required fields."""
    d = RoutingDecision(
        schemas=[],
        available={"a"},
        denied={"b"},
        task_class="COMPLEX",
        enforcement="strict",
    )
    assert d.task_class == "COMPLEX"
    assert d.enforcement == "strict"
    assert "a" in d.available
    assert "b" in d.denied


# ── 2. BUILTIN_ROUTES coverage ──────────────────────────────


def test_builtin_routes_cover_core_tools():
    """BUILTIN_ROUTES covers all core tools."""
    expected = {
        "run_code", "code_analysis", "run_command", "system_health",
        "read_file", "file_ops", "web_search", "fetch",
        "gmail_read", "gmail_write", "memory", "agent",
        "generate_image", "analyze_image", "edit_image",
        "think", "web_design", "task_state",
    }
    assert expected.issubset(set(BUILTIN_ROUTES.keys()))


def test_tool_route_has_capabilities():
    """Every BUILTIN_ROUTES entry has at least one CapabilityTag."""
    for name, route in BUILTIN_ROUTES.items():
        assert len(route.capabilities) > 0, f"{name} has no capabilities"
        assert route.name == name


def test_web_search_fallback_is_fetch():
    """web_search's fallback is declared as fetch."""
    fetch_route = BUILTIN_ROUTES["fetch"]
    assert fetch_route.fallback_for == "web_search"


# ── 3. CapabilityRouter.resolve() ───────────────────────────


def test_resolve_returns_routing_decision():
    """resolve() returns a RoutingDecision, not a raw list."""
    router = _make_router()
    with patch("nally.tools.filter.tool_filter") as mock_filter:
        mock_filter._ready = True
        mock_filter.select.return_value = [
            {"function": {"name": "run_command", "description": "Run a shell command"}},
            {"function": {"name": "read_file", "description": "Read a file"}},
        ]
        decision = router.resolve("run a command", task_class="SIMPLE")

    assert isinstance(decision, RoutingDecision)
    assert len(decision.schemas) == 2
    assert "run_command" in decision.available


def test_resolve_empty_query_returns_schemas():
    """resolve() with empty query still returns schemas."""
    router = _make_router()
    with patch("nally.tools.filter.tool_filter") as mock_filter:
        mock_filter._ready = True
        mock_filter.select.return_value = [
            {"function": {"name": "system_health"}},
        ]
        decision = router.resolve("")

    assert isinstance(decision, RoutingDecision)
    assert len(decision.schemas) >= 1


def test_resolve_task_class_forwarded():
    """resolve() forwards task_class to RoutingDecision."""
    router = _make_router()
    with patch("nally.tools.filter.tool_filter") as mock_filter:
        mock_filter._ready = True
        mock_filter.select.return_value = []
        decision = router.resolve("x", task_class="HIGH_STAKES")

    assert decision.task_class == "HIGH_STAKES"


def test_resolve_permission_deny_filters_tool():
    """resolve() with enforce_permissions=True drops DENY tools."""
    router = _make_router()
    with patch("nally.tools.filter.tool_filter") as mock_filter, \
         patch("nally.tools.permissions.gate") as mock_gate:
        mock_filter._ready = True
        mock_filter.select.return_value = [
            {"function": {"name": "run_command", "description": "Run a shell command"}},
            {"function": {"name": "read_file", "description": "Read a file"}},
        ]
        mock_gate.check.side_effect = lambda name, args: "deny" if name == "run_command" else "allow"

        decision = router.resolve("run a command", enforce_permissions=True)

    assert "run_command" in decision.denied
    assert "run_command" not in decision.available
    assert "read_file" in decision.available
    assert len(decision.schemas) == 1


def test_resolve_permission_ask_stays_in_schemas():
    """ASK tools remain in schemas (graph owns the approval UX)."""
    router = _make_router()
    with patch("nally.tools.filter.tool_filter") as mock_filter, \
         patch("nally.tools.permissions.gate") as mock_gate:
        mock_filter._ready = True
        mock_filter.select.return_value = [
            {"function": {"name": "run_command", "description": "Run a shell command"}},
        ]
        mock_gate.check.return_value = "ask"

        decision = router.resolve("run a command", enforce_permissions=True)

    assert len(decision.schemas) == 1
    assert "run_command" in decision.available
    assert "run_command" not in decision.denied


def test_resolve_enforcement_strict():
    """resolve() with enforce_permissions=True sets enforcement=strict."""
    router = _make_router()
    with patch("nally.tools.filter.tool_filter") as mock_filter:
        mock_filter._ready = True
        mock_filter.select.return_value = []
        decision = router.resolve("x", enforce_permissions=True)

    assert decision.enforcement == "strict"


def test_resolve_enforcement_permissive():
    """resolve() with enforce_permissions=False sets enforcement=permissive."""
    router = _make_router()
    with patch("nally.tools.filter.tool_filter") as mock_filter:
        mock_filter._ready = True
        mock_filter.select.return_value = []
        decision = router.resolve("x", enforce_permissions=False)

    assert decision.enforcement == "permissive"


# ── 4. suggest_fallback() ───────────────────────────────────


def test_suggest_fallback_web_search_to_fetch():
    """suggest_fallback('web_search') returns fetch."""
    router = _make_router()
    fallback = router.suggest_fallback("web_search", "search the web")
    assert fallback is not None
    assert fallback.name == "fetch"
    assert fallback.fallback_for == "web_search"


def test_suggest_fallback_run_command_to_run_code():
    """suggest_fallback('run_command') returns run_code (same capability)."""
    router = _make_router()
    fallback = router.suggest_fallback("run_command", "execute code")
    assert fallback is not None
    assert fallback.name == "run_code"


def test_suggest_fallback_read_file_to_file_ops():
    """suggest_fallback('read_file') returns file_ops (overlapping capability)."""
    router = _make_router()
    fallback = router.suggest_fallback("read_file", "read a file")
    assert fallback is not None
    assert fallback.name == "file_ops"


def test_suggest_fallback_no_alternative():
    """suggest_fallback() returns None for a tool with no alternatives."""
    router = _make_router()
    # 'think' is the only THINKING tool — no fallback
    fallback = router.suggest_fallback("think", "think about it")
    assert fallback is None


def test_suggest_fallback_unknown_tool():
    """suggest_fallback() returns None for an unknown tool name."""
    router = _make_router()
    fallback = router.suggest_fallback("nonexistent_tool", "do something")
    assert fallback is None


def test_suggest_fallback_priority_order():
    """suggest_fallback() returns highest-priority alternative first."""
    router = _make_router()
    # Both run_command and run_code have CODE_EXECUTION capability.
    # run_command has priority=2, run_code has priority=1.
    # When failing run_code, the fallback should be run_command (higher priority).
    fallback = router.suggest_fallback("run_code", "execute code")
    assert fallback is not None
    assert fallback.name == "run_command"


# ── 5. SubAgent tool selection ───────────────────────────────


def test_subagent_uses_capability_router():
    """SubAgent._get_filtered_tools() calls capability_router.resolve()."""
    from nally.subagent.agent import _get_filtered_tools

    with patch("nally.tools.capability_router.capability_router") as mock_router:
        mock_decision = MagicMock()
        mock_decision.schemas = [{"function": {"name": "run_command"}}]
        mock_router.resolve.return_value = mock_decision

        result = _get_filtered_tools("run a command")

    mock_router.resolve.assert_called_once_with("run a command")
    assert result == [{"function": {"name": "run_command"}}]


def test_subagent_fallback_on_router_error():
    """SubAgent._get_filtered_tools() falls back to full registry on error."""
    from nally.subagent.agent import _get_filtered_tools

    def _boom(query):
        raise ConnectionError("router unavailable")

    with patch("nally.tools.capability_router.capability_router.resolve", side_effect=_boom), \
         patch("nally.tools.registry.registry") as mock_reg:
        mock_reg.tools = {"run_command": Tool("run_command", "Run a shell command")}

        result = _get_filtered_tools("run a command")

    assert len(result) == 1
    assert result[0]["function"]["name"] == "run_command"


# ── 6. Tool.capabilities field ───────────────────────────────


def test_tool_capabilities_default_empty():
    """Tool.capabilities defaults to empty set."""
    t = Tool("test", "test tool")
    assert t.capabilities == set()


def test_tool_capabilities_set():
    """Tool.capabilities can be set at construction."""
    t = Tool("test", "test tool", capabilities={"code_execution", "system"})
    assert "code_execution" in t.capabilities
    assert "system" in t.capabilities


# ── 7. get_route / register_route ───────────────────────────


def test_get_route_builtin():
    """get_route() returns routes for built-in tools."""
    router = _make_router()
    route = router.get_route("web_search")
    assert route is not None
    assert route.name == "web_search"
    assert CapabilityTag.WEB in route.capabilities


def test_get_route_unknown():
    """get_route() returns None for unknown tools."""
    router = _make_router()
    assert router.get_route("nonexistent") is None


def test_register_route():
    """register_route() adds a custom route."""
    router = _make_router()
    custom = ToolRoute(
        name="mcp_custom_tool",
        capabilities={CapabilityTag.MCP},
        priority=0,
    )
    router.register_route(custom)
    assert router.get_route("mcp_custom_tool") is custom


# ── 8. CapabilityTag enum ───────────────────────────────────


def test_capability_tag_values():
    """CapabilityTag has all expected tags."""
    expected = {
        "code_execution", "file_system", "web", "email", "memory",
        "subagent", "image", "system", "thinking", "mcp",
    }
    actual = {tag.value for tag in CapabilityTag}
    assert expected == actual
