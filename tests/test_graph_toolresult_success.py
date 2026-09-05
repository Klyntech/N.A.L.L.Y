"""Graph/Bridge consume ToolResult.ok as authoritative success."""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from nally.tools.registry import Tool, ToolRegistry
from nally.tools.result import ToolResult


def _stub_graph_deps():
    """Allow importing graph helpers without full langgraph install."""

    def ensure(name, pkg=False):
        if name in sys.modules:
            mod = sys.modules[name]
            if pkg and not hasattr(mod, "__path__"):
                mod = types.ModuleType(name)
                sys.modules[name] = mod
        else:
            mod = types.ModuleType(name)
            sys.modules[name] = mod
        if pkg:
            mod.__path__ = []
        return mod

    ensure("langgraph", pkg=True)
    ensure("langgraph.checkpoint", pkg=True)
    mem = ensure("langgraph.checkpoint.memory")
    mem.MemorySaver = type("MemorySaver", (), {})
    g = ensure("langgraph.graph", pkg=True)
    g.END = "END"
    g.START = "START"
    g.StateGraph = type("StateGraph", (), {})
    msg = ensure("langgraph.graph.message")
    msg.add_messages = lambda x: x


def _install_fake_bridge_registry(fake):
    web = types.ModuleType("nally.web")
    bh = types.ModuleType("nally.web.bridge_handler")
    bh.bridge_registry = fake
    web.bridge_handler = bh
    sys.modules["nally.web"] = web
    sys.modules["nally.web.bridge_handler"] = bh


def test_execute_result_ok_true_for_success():
    reg = ToolRegistry()

    class T(Tool):
        def __init__(self):
            super().__init__("t_ok", "ok")

        def execute(self, **kw):
            return "hello contains Error word but is fine"

    reg.register(T())
    tr = reg.execute_result("t_ok", {})
    assert tr.ok is True
    assert "Error" in str(tr.value)


def test_execute_result_ok_false_for_failure():
    reg = ToolRegistry()

    class T(Tool):
        def __init__(self):
            super().__init__("t_err", "err")

        def execute(self, **kw):
            return "Error: boom"

    reg.register(T())
    tr = reg.execute_result("t_err", {})
    assert tr.ok is False


def test_failed_non_error_prefix_still_failure_when_structured():
    reg = ToolRegistry()

    class T(Tool):
        def __init__(self):
            super().__init__("t_struct_fail", "f")

        def execute(self, **kw):
            return ToolResult.failure(error="remote device offline", value="offline")

    reg.register(T())
    tr = reg.execute_result("t_struct_fail", {})
    assert tr.ok is False
    text, ok = reg.execute("t_struct_fail", {})
    assert ok is False
    assert "error" in text.lower()


def test_successful_result_containing_error_word_still_success():
    reg = ToolRegistry()

    class T(Tool):
        def __init__(self):
            super().__init__("t_msg", "m")

        def execute(self, **kw):
            return ToolResult.success(value="Logged: Error count=0")

    reg.register(T())
    tr = reg.execute_result("t_msg", {})
    assert tr.ok is True
    assert "Error" in str(tr.value)


def test_graph_retry_uses_ok_not_string_reconstruction():
    _stub_graph_deps()
    from nally.agent import graph as g

    calls = {"n": 0}

    def fake_execute_result(name, args):
        calls["n"] += 1
        if calls["n"] == 1:
            return ToolResult.failure(error="Error: timeout connecting", value="timeout")
        return ToolResult.success(value="recovered")

    with patch.object(g, "registry") as reg:
        reg.execute_result.side_effect = fake_execute_result
        tr = g._execute_tool_with_retry("web_search", {}, "tc1")
    assert tr.ok is True
    assert tr.value == "recovered"
    assert calls["n"] == 2


def test_graph_non_transient_failure_no_retry():
    _stub_graph_deps()
    from nally.agent import graph as g

    calls = {"n": 0}

    def fake_execute_result(name, args):
        calls["n"] += 1
        return ToolResult.failure(error="Error: file not found", value="missing")

    with patch.object(g, "registry") as reg:
        reg.execute_result.side_effect = fake_execute_result
        tr = g._execute_tool_with_retry("web_search", {}, "tc1")
    assert tr.ok is False
    assert calls["n"] == 1


def test_graph_destructive_no_retry():
    _stub_graph_deps()
    from nally.agent import graph as g

    calls = {"n": 0}

    def fake_execute_result(name, args):
        calls["n"] += 1
        return ToolResult.failure(error="Error: timeout", value="timeout")

    with patch.object(g, "registry") as reg:
        reg.execute_result.side_effect = fake_execute_result
        tr = g._execute_tool_with_retry("run_command", {"command": "x"}, "tc1")
    assert tr.ok is False
    assert calls["n"] == 1


def test_bridge_remote_failure_cannot_become_success():
    from nally.tools.bridge import BridgeTool

    tool = BridgeTool()

    class FakeReg:
        devices = {"desktop": MagicMock(tools=["run_command"], device_id="desktop")}

        def get_device(self, name):
            return self.devices.get(name)

        async def send_tool_request(self, device_id, tool, args):
            return ("device offline", False)

    _install_fake_bridge_registry(FakeReg())
    tr = tool.execute(device="desktop", tool="run_command", args={"command": "dir"})
    assert isinstance(tr, ToolResult)
    assert tr.ok is False

    reg = ToolRegistry()
    reg.register(tool)
    out = reg.execute_result(
        "bridge_execute",
        {"device": "desktop", "tool": "run_command", "args": {"command": "dir"}},
    )
    assert out.ok is False


def test_bridge_remote_success_remains_success():
    from nally.tools.bridge import BridgeTool

    tool = BridgeTool()

    class FakeReg:
        devices = {"desktop": MagicMock(tools=["run_command"], device_id="desktop")}

        def get_device(self, name):
            return self.devices.get(name)

        async def send_tool_request(self, device_id, tool, args):
            return ("file list ok", True)

    _install_fake_bridge_registry(FakeReg())
    tr = tool.execute(device="desktop", tool="run_command", args={"command": "dir"})
    assert isinstance(tr, ToolResult)
    assert tr.ok is True
    assert tr.value == "file list ok"


def test_legacy_tools_still_work_through_adapter():
    reg = ToolRegistry()

    class Legacy(Tool):
        def __init__(self):
            super().__init__("legacy", "l")

        def execute(self, **kw):
            return "plain ok"

    reg.register(Legacy())
    text, ok = reg.execute("legacy", {})
    assert ok is True
    assert text == "plain ok"
    tr = reg.execute_result("legacy", {})
    assert tr.ok is True
