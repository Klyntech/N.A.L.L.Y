"""Regression tests for structured ToolResult execution contract."""

from __future__ import annotations

import pytest

from nally.core.errors import ToolError
from nally.tools.registry import Tool, ToolRegistry, _result_is_success
from nally.tools.result import ToolResult, _safe_metadata


@pytest.fixture
def reg():
    return ToolRegistry()


def _register(reg: ToolRegistry, tool: Tool):
    reg.register(tool)
    return tool


class _StrOk(Tool):
    def __init__(self):
        super().__init__("str_ok", "legacy success")

    def execute(self, **kwargs):
        return "all good"


class _StrErr(Tool):
    def __init__(self):
        super().__init__("str_err", "legacy failure")

    def execute(self, **kwargs):
        return "Error: something broke"


class _StructOk(Tool):
    def __init__(self):
        super().__init__("struct_ok", "structured success")

    def execute(self, **kwargs):
        return ToolResult.success(value="structured-ok", phase="test")


class _StructErr(Tool):
    def __init__(self):
        super().__init__("struct_err", "structured failure")

    def execute(self, **kwargs):
        return ToolResult.failure(error="Error: structured-fail", phase="test")


class _Raises(Tool):
    def __init__(self):
        super().__init__("raises", "raises")

    def execute(self, **kwargs):
        raise RuntimeError("unexpected")


class _ToolErrorTool(Tool):
    def __init__(self):
        super().__init__("tool_error", "tool error")

    def execute(self, **kwargs):
        raise ToolError(code="bad_args", message="invalid arguments")


class _NoneTool(Tool):
    def __init__(self):
        super().__init__("none_tool", "returns none")

    def execute(self, **kwargs):
        return None


def test_successful_legacy_string(reg):
    _register(reg, _StrOk())
    tr = reg.execute_result("str_ok", {})
    assert tr.ok is True
    assert tr.value == "all good"
    assert tr.error is None
    text, ok = reg.execute("str_ok", {})
    assert ok is True
    assert text == "all good"


def test_tool_failure_legacy_string(reg):
    _register(reg, _StrErr())
    tr = reg.execute_result("str_err", {})
    assert tr.ok is False
    assert tr.to_llm_text().lower().startswith("error")
    text, ok = reg.execute("str_err", {})
    assert ok is False
    # Failure must not look like success
    assert _result_is_success("str_err", text) is False


def test_unknown_tool(reg):
    tr = reg.execute_result("definitely_missing_tool", {})
    assert tr.ok is False
    assert "not found" in (tr.error or "").lower()
    text, ok = reg.execute("definitely_missing_tool", {})
    assert ok is False


def test_exception_during_execution(reg):
    _register(reg, _Raises())
    tr = reg.execute_result("raises", {})
    assert tr.ok is False
    assert "unexpected" in (tr.error or "")
    text, ok = reg.execute("raises", {})
    assert ok is False
    assert text.lower().startswith("error")


def test_tool_error_invalid_arguments(reg):
    _register(reg, _ToolErrorTool())
    tr = reg.execute_result("tool_error", {})
    assert tr.ok is False
    text, ok = reg.execute("tool_error", {})
    assert ok is False
    assert "invalid" in text.lower() or "error" in text.lower()


def test_legacy_string_returning_tool(reg):
    _register(reg, _StrOk())
    tr = ToolResult.from_legacy("str_ok", "plain output")
    assert tr.ok is True
    tr = ToolResult.from_legacy("str_ok", "Error: no")
    assert tr.ok is False


def test_structured_returning_tool(reg):
    _register(reg, _StructOk())
    tr = reg.execute_result("struct_ok", {})
    assert tr.ok is True
    assert tr.value == "structured-ok"
    _register(reg, _StructErr())
    tr = reg.execute_result("struct_err", {})
    assert tr.ok is False


def test_none_return_is_success(reg):
    _register(reg, _NoneTool())
    tr = reg.execute_result("none_tool", {})
    assert tr.ok is True


def test_caller_compatibility_tuple(reg):
    _register(reg, _StrOk())
    _register(reg, _StrErr())
    assert isinstance(reg.execute("str_ok", {}), tuple)
    assert len(reg.execute("str_ok", {})) == 2
    assert reg.execute("str_ok", {})[1] is True
    assert reg.execute("str_err", {})[1] is False


def test_safe_metadata_strips_secrets():
    dirty = {
        "tool": "x",
        "access_token": "sekret",
        "refresh_token": "r",
        "password": "p",
        "api_key": "k",
        "note": "ok",
    }
    clean = _safe_metadata(dirty)
    assert "access_token" not in clean
    assert "refresh_token" not in clean
    assert "password" not in clean
    assert "api_key" not in clean
    assert clean.get("note") == "ok"
    assert clean.get("tool") == "x"


def test_failure_cannot_look_like_success(reg):
    _register(reg, _StrErr())
    tr = reg.execute_result("str_err", {})
    assert tr.ok is False
    # to_llm_text must remain failure under string success detector
    assert _result_is_success("str_err", tr.to_llm_text()) is False
    # accidental success() with Error value would still fail detector via from_legacy
    bad = ToolResult.success(value="Error: leaked failure")
    # explicit ok=True but text starts with Error — callers using as_tuple trust ok flag
    # boundary: from_legacy must not mark Error strings as ok
    adapted = ToolResult.from_legacy("t", "Error: leaked failure")
    assert adapted.ok is False


def test_serialization_logging_safety(reg):
    _register(reg, _StructOk())
    tr = reg.execute_result("struct_ok", {})
    # metadata must not contain obvious secrets even if tool put them there
    sneaky = ToolResult.success(value="x", access_token="nope", tool="struct_ok")
    from nally.tools.result import _safe_metadata

    assert "access_token" not in _safe_metadata(sneaky.metadata)
