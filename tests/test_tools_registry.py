"""Tests for nally.tools.registry — ToolError handling and success detection."""

import pytest
from nally.core.errors import ToolError
from nally.tools.registry import ToolRegistry, Tool, _result_is_success


class TestResultIsSuccess:
    def test_empty_result_is_success(self):
        assert _result_is_success("test_tool", "") is True

    def test_none_result_is_success(self):
        assert _result_is_success("test_tool", None) is True

    def test_error_prefix_is_failure(self):
        assert _result_is_success("test_tool", "Error: something broke") is False

    def test_error_prefix_case_insensitive(self):
        assert _result_is_success("test_tool", "error: lowercase") is False

    def test_toolerror_format_is_failure(self):
        """ToolError.to_llm_format() starts with 'Error:' — should be detected."""
        err = ToolError.failed("my_tool", "it broke")
        result = err.to_llm_format()
        assert _result_is_success("my_tool", result) is False

    def test_success_message_with_error_word(self):
        """A success message that contains 'Error' but doesn't start with it."""
        assert _result_is_success("test_tool", "Found no Error in the file") is True

    def test_run_command_zero_exit(self):
        assert _result_is_success("run_command", "Output: hello\nExit code: 0") is True

    def test_run_command_nonzero_exit(self):
        assert _result_is_success("run_command", "Output: something\nExit code: 1") is False

    def test_run_command_no_exit_code(self):
        assert _result_is_success("run_command", "Output: hello world") is True


class TestToolRegistryExecute:
    def test_tool_not_found(self):
        reg = ToolRegistry()
        result, success = reg.execute("nonexistent_tool", {})
        assert "not found" in result.lower()
        assert success is False

    def test_tool_error_exception(self):
        """Tools raising ToolError should return LLM-formatted error."""
        reg = ToolRegistry()

        class FailingTool(Tool):
            def __init__(self):
                super().__init__(name="failing_tool", description="fails")
            def execute(self, **kwargs):
                raise ToolError.failed("failing_tool", "intentional failure")

        reg.register(FailingTool())
        result, success = reg.execute("failing_tool", {})
        assert success is False
        assert "Error" in result
        assert "intentional failure" in result

    def test_tool_generic_exception(self):
        """Tools raising generic exceptions should return error string."""
        reg = ToolRegistry()

        class CrashTool(Tool):
            def __init__(self):
                super().__init__(name="crash_tool", description="crashes")
            def execute(self, **kwargs):
                raise RuntimeError("boom")

        reg.register(CrashTool())
        result, success = reg.execute("crash_tool", {})
        assert success is False
        assert "Error" in result
        assert "RuntimeError" in result

    def test_successful_tool(self):
        reg = ToolRegistry()

        class OkTool(Tool):
            def __init__(self):
                super().__init__(name="ok_tool", description="works")
            def execute(self, **kwargs):
                return "All good"

        reg.register(OkTool())
        result, success = reg.execute("ok_tool", {})
        assert success is True
        assert result == "All good"
