"""tool_executor._execute_single previously-uncovered paths.

Regression tests for three undefined-name bugs that lived in the fan-out
success path (all raised NameError; two were masked by broad try/except):
1. MAX_TOOL_OUTPUT truncation on success (fatal — every successful model
   tool call failed here).
2. Idempotent skip via task_id (NameError swallowed -> re-execution).
3. Scratchpad update on success (`tool_success` vs `success` NameError
   collapsed verification + scratchpad updates).
"""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from nally.tools.result import ToolResult


def _state(tool_name, args, **extra):
    messages = [
        HumanMessage(content="do it"),
        AIMessage(
            content="",
            tool_calls=[{"name": tool_name, "args": args, "id": "tc1", "type": "tool_call"}],
        ),
    ]
    base = {
        "messages": messages,
        "thread_id": "test-executor-paths",
        "session_id": "test-executor-paths",
        "iteration": 0,
        "tool_calls_total": 0,
    }
    base.update(extra)
    return base


@pytest.fixture
def executor_harness(monkeypatch):
    """Stub everything around _execute_single except the code under test."""
    import nally.agent.graph as g

    monkeypatch.setattr(g, "_check_abort", lambda thread_id: False)
    monkeypatch.setattr(g, "checkpointer", None)
    monkeypatch.setattr(g, "checkpoint_store", None)

    tracer = MagicMock()
    tracer.get_current_span.return_value = None
    monkeypatch.setattr(g, "tracer", tracer)

    hooks = MagicMock()
    hooks.run_pre_tool.return_value = MagicMock(decision="proceed", reason="")
    hooks.run_post_tool.return_value = MagicMock(additionalContext=None)
    monkeypatch.setattr(
        "nally.core.hooks.manager.get_hook_manager", lambda: hooks
    )

    task_state_manager = MagicMock()
    task_state_manager.get.return_value = MagicMock(
        files_created=[], key_decisions=[]
    )
    monkeypatch.setattr(
        "nally.tools.task_state.task_state_manager", task_state_manager
    )

    receipts = MagicMock()
    receipts.get_idempotent.return_value = None
    monkeypatch.setattr("nally.tools.receipts.receipt_store", receipts)

    import nally.config as cfg

    monkeypatch.setattr(cfg, "HARNESS_ENABLED", True)
    monkeypatch.setattr(cfg, "HARNESS_VERIFY_ENABLED", False)
    monkeypatch.setattr(cfg, "HARNESS_SCRATCHPAD_ENABLED", True)

    return g


class TestSuccessPathTruncation:
    def test_success_returns_tool_message(self, executor_harness):
        g = executor_harness
        with patch.object(
            g,
            "_execute_tool_with_retry",
            return_value=ToolResult.success(value="sys-ok"),
        ):
            out = g.tool_executor(_state("system_health", {}))

        assert len(out["messages"]) == 1
        msg = out["messages"][0]
        assert msg.content == "sys-ok"
        assert out["tool_calls_total"] == 1

    def test_long_result_truncated_to_max_tool_output(self, executor_harness):
        import nally.config as cfg

        g = executor_harness
        big = "x" * (cfg.MAX_TOOL_OUTPUT + 100)
        with patch.object(
            g,
            "_execute_tool_with_retry",
            return_value=ToolResult.success(value=big),
        ):
            out = g.tool_executor(_state("system_health", {}))

        content = out["messages"][0].content
        assert len(content) == cfg.MAX_TOOL_OUTPUT
        assert "NameError" not in content


class TestIdempotentSkip:
    def test_cached_task_id_skips_execution(self, executor_harness):
        g = executor_harness
        with (
            patch("nally.tools.receipts.receipt_store") as receipts,
            patch.object(g, "_execute_tool_with_retry") as runner,
        ):
            receipts.get_idempotent.return_value = "cached-output"
            out = g.tool_executor(
                _state("system_health", {"task_id": "tid-1"})
            )

        runner.assert_not_called()
        assert out["messages"][0].content == "cached-output"


class TestScratchpadUpdate:
    def test_success_records_scratchpad_action(self, executor_harness):
        g = executor_harness
        scratchpad = MagicMock()
        with patch.object(
            g,
            "_execute_tool_with_retry",
            return_value=ToolResult.success(value="sys-ok"),
        ):
            out = g.tool_executor(
                _state("system_health", {}, _scratchpad=scratchpad)
            )

        assert out["messages"][0].content == "sys-ok"
        scratchpad.add_action.assert_called_once()
        scratchpad.add_result.assert_called_once()
