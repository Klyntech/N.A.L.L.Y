"""Tests for nally.agent.graph — retry logic, should_continue emit behavior, and topology."""

import time
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from nally.agent.graph import (
    _call_llm_with_retry,
    _has_duplicate_tool_calls,
    should_continue,
)
from nally.core.errors import LLMError

# ── BUG 6: model override retries ─────────────────────────


class TestCallLlmWithRetry:
    """Test that _call_llm_with_retry retries on transient errors, including with model override."""

    def _make_llm_client(self, side_effect=None, return_value=None):
        client = MagicMock()
        if side_effect:
            client.chat_with_model.side_effect = side_effect
            client.chat.side_effect = side_effect
        else:
            client.chat_with_model.return_value = return_value or MagicMock()
            client.chat.return_value = return_value or MagicMock()
        return client

    def _mock_emit(self):
        return MagicMock()

    @patch("nally.agent.graph._stream_with_emit", side_effect=Exception("stream down"))
    def test_model_override_retries_on_transient_error(self, _mock_stream):
        """chat_with_model should be retried _MAX_RETRIES times on transient errors."""
        from nally.agent.graph import _MAX_RETRIES

        client = self._make_llm_client(side_effect=Exception("Error 503: overloaded"))
        emit = self._mock_emit()
        messages = [{"role": "user", "content": "hello"}]

        with pytest.raises(LLMError, match="overloaded"):
            _call_llm_with_retry(client, messages, None, "test", emit, model="custom-model")

        assert client.chat_with_model.call_count == _MAX_RETRIES

    @patch("nally.agent.graph._stream_with_emit", side_effect=Exception("stream down"))
    def test_model_override_retries_on_429(self, _mock_stream):
        """chat_with_model should be retried on rate-limit errors."""
        from nally.agent.graph import _MAX_RETRIES

        client = self._make_llm_client(side_effect=Exception("429 rate limit"))
        emit = self._mock_emit()
        messages = [{"role": "user", "content": "hello"}]

        with pytest.raises(LLMError, match="Rate limit"):
            _call_llm_with_retry(client, messages, None, "test", emit, model="custom-model")

        assert client.chat_with_model.call_count == _MAX_RETRIES

    @patch("nally.agent.graph._stream_with_emit", side_effect=Exception("stream down"))
    def test_model_override_succeeds_after_retry(self, _mock_stream):
        """chat_with_model should succeed on second attempt after transient failure."""
        from openai.types.chat import ChatCompletion, ChatCompletionMessage
        from openai.types.chat.chat_completion import Choice

        ok_response = ChatCompletion(
            id="test",
            choices=[Choice(finish_reason="stop", index=0, message=ChatCompletionMessage(role="assistant", content="ok"))],
            created=0,
            model="custom-model",
            object="chat.completion",
        )

        client = MagicMock()
        client.chat_with_model.side_effect = [
            Exception("Error 502: bad gateway"),
            ok_response,
        ]
        emit = self._mock_emit()
        messages = [{"role": "user", "content": "hello"}]

        result = _call_llm_with_retry(client, messages, None, "test", emit, model="custom-model")
        assert result == ok_response
        assert client.chat_with_model.call_count == 2

    @patch("nally.agent.graph._stream_with_emit", side_effect=Exception("stream down"))
    def test_no_model_uses_chat_with_retry(self, _mock_stream):
        """Without model override, llm.chat should be called (not chat_with_model)."""
        from nally.agent.graph import _RATE_LIMIT_RETRIES

        client = self._make_llm_client(side_effect=Exception("Error 500"))
        emit = self._mock_emit()
        messages = [{"role": "user", "content": "hello"}]

        with pytest.raises(LLMError):
            _call_llm_with_retry(client, messages, None, "test", emit)

        assert client.chat.call_count == _RATE_LIMIT_RETRIES
        assert client.chat_with_model.call_count == 0


# ── BUG 1: should_continue emits system_notice ──────────────


class TestShouldContinueEmit:
    """Test that should_continue emits system_notice on silent-stop branches."""

    def _make_state(self, **overrides):
        state = {
            "messages": [HumanMessage(content="hi"), AIMessage(content="ok")],
            "iteration": 0,
            "max_iterations": 10,
            "error_count": 0,
            "last_error": None,
            "tool_calls_total": 0,
            "thread_id": "test-thread",
            "plan": None,
            "plan_status": "",
            "step_results": {},
            "current_step_index": 0,
            "model_override": None,
            "start_time": 0.0,
            "tools": [],
        }
        state.update(overrides)
        return state

    @patch("nally.agent.graph._check_abort", return_value=False)
    def test_wall_clock_emits_notice(self, _mock_abort):
        """Wall-clock budget stop should emit system_notice."""
        from nally.agent.graph import MAX_AGENT_WALL_TIME

        emit = MagicMock()
        with patch("nally.agent.graph._get_emit", return_value=emit):
            state = self._make_state(start_time=time.time() - MAX_AGENT_WALL_TIME - 10)
            result = should_continue(state)

        assert result == "end"
        emit.assert_called_once()
        call_args = emit.call_args
        assert call_args[0][0] == "system_notice"
        assert "time budget" in call_args[0][1]["text"]

    @patch("nally.agent.graph._check_abort", return_value=False)
    def test_max_iterations_emits_notice(self, _mock_abort):
        """Max iterations stop should emit system_notice."""
        emit = MagicMock()
        with patch("nally.agent.graph._get_emit", return_value=emit):
            state = self._make_state(iteration=10, max_iterations=10)
            result = should_continue(state)

        assert result == "end"
        emit.assert_called_once()
        call_args = emit.call_args
        assert call_args[0][0] == "system_notice"
        assert "step limit" in call_args[0][1]["text"]

    @patch("nally.agent.graph._check_abort", return_value=False)
    def test_doom_loop_emits_notice(self, _mock_abort):
        """Doom loop stop should emit system_notice."""
        emit = MagicMock()
        with patch("nally.agent.graph._get_emit", return_value=emit):
            with patch("nally.agent.graph._has_duplicate_tool_calls", return_value=True):
                state = self._make_state()
                result = should_continue(state)

        assert result == "end"
        emit.assert_called_once()
        call_args = emit.call_args
        assert call_args[0][0] == "system_notice"
        assert "repeating" in call_args[0][1]["text"]

    @patch("nally.agent.graph._check_abort", return_value=False)
    def test_no_emit_when_none(self, _mock_abort):
        """should_continue should not crash when emit is None."""
        with patch("nally.agent.graph._get_emit", return_value=None):
            state = self._make_state(iteration=10, max_iterations=10)
            result = should_continue(state)

        assert result == "end"

    @patch("nally.agent.graph._check_abort", return_value=False)
    def test_abort_does_not_emit_notice(self, _mock_abort):
        """Abort checkpoint should NOT emit system_notice (user-triggered)."""
        emit = MagicMock()
        with patch("nally.agent.graph._get_emit", return_value=emit):
            state = self._make_state()
            # Force abort check to return True
            with patch("nally.agent.graph._check_abort", return_value=True):
                result = should_continue(state)

        assert result == "end"
        emit.assert_not_called()


# ── _has_duplicate_tool_calls ─────────────────────────────


class TestHasDuplicateToolCalls:
    """Test doom loop detection."""

    def test_no_tool_calls(self):
        msgs = [HumanMessage(content="hi"), AIMessage(content="ok")]
        assert _has_duplicate_tool_calls(msgs) is False

    def test_duplicates_detected(self):
        tc = {"id": "tc1", "name": "run_command", "args": {"command": "ls"}}
        msgs = [
            AIMessage(content="", tool_calls=[tc]),
            AIMessage(content="", tool_calls=[tc]),
            AIMessage(content="", tool_calls=[tc]),
        ]
        assert _has_duplicate_tool_calls(msgs) is True

    def test_different_args_not_duplicates(self):
        msgs = [
            AIMessage(content="", tool_calls=[{"id": "tc1", "name": "run_command", "args": {"command": "ls"}}]),
            AIMessage(content="", tool_calls=[{"id": "tc2", "name": "run_command", "args": {"command": "pwd"}}]),
            AIMessage(content="", tool_calls=[{"id": "tc3", "name": "run_command", "args": {"command": "whoami"}}]),
        ]
        assert _has_duplicate_tool_calls(msgs) is False


# ── Graph topology tests ──────────────────────────────────


class TestGraphTopology:
    """Test that the graph topology is correct when PLAN_ENABLED is on/off."""

    def test_plan_enabled_has_critique_node(self):
        """When PLAN_ENABLED=true, the graph should contain a 'critique' node."""
        with patch("nally.agent.graph.PLAN_ENABLED", True):
            from langgraph.checkpoint.memory import MemorySaver

            with patch("nally.agent.graph._create_checkpointer", return_value=MemorySaver()):
                from nally.agent.graph import create_agent_graph

                graph = create_agent_graph()
                compiled = graph.get_graph()
                node_names = set(compiled.nodes.keys())
                assert "critique" in node_names
                assert "planner" in node_names
                assert "execute_step" in node_names

    def test_plan_disabled_no_critique_node(self):
        """When PLAN_ENABLED=false, no critique node should exist."""
        with patch("nally.agent.graph.PLAN_ENABLED", False):
            from langgraph.checkpoint.memory import MemorySaver

            with patch("nally.agent.graph._create_checkpointer", return_value=MemorySaver()):
                from nally.agent.graph import create_agent_graph

                graph = create_agent_graph()
                compiled = graph.get_graph()
                node_names = set(compiled.nodes.keys())
                assert "critique" not in node_names
                assert "planner" not in node_names
