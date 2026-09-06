"""Gate C: R5 E2E composition — mocked-LLM + real graph + hermetic tools.

Proves the machine composes: agent.process() -> graph -> tools -> verify.
All LLM calls are mocked; no network. Tools that touch disk use tmp paths.
Traces are asserted via route decisions and final responses, not just DONE.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nally.agent.core import NallyAgent
from nally.agent.task_router import Strategy


@pytest.fixture
def stubbed_agent(monkeypatch, tmp_path):
    from nally.agent import core as core_mod

    store = MagicMock()
    store.get_user_facts.return_value = "No user facts stored yet."
    store.get_conversation_summaries_text.return_value = ""
    store.get_recent_episodes_text.return_value = ""
    store.load_messages.return_value = []
    monkeypatch.setattr(core_mod, "memory_store", store)
    monkeypatch.setattr(core_mod, "SESSION_ID", "test-e2e")
    # Avoid background decay thread touching real DB
    monkeypatch.setattr(core_mod.memory_store, "reset_stale_facts", lambda: None)
    monkeypatch.setattr(core_mod.memory_store, "decay_old_memories", lambda: None)
    return core_mod.NallyAgent(session_id="test-e2e")


def _mock_llm_for_react(tool_name="read_file", tool_args=None, final_answer="done"):
    """Helper to mock _call_llm_with_retry to emit one tool call then a final answer."""
    tool_args = tool_args or {}
    call_count = {"n": 0}

    def fake_llm(llm_client, openai_messages, tools, cache_key, emit, model=None):
        call_count["n"] += 1
        mock_resp = MagicMock()
        msg = MagicMock()
        if call_count["n"] == 1:
            msg.content = ""
            tc = MagicMock()
            tc.id = "call_1"
            tc.function.name = tool_name
            tc.function.arguments = json.dumps(tool_args)
            msg.tool_calls = [tc]
        else:
            msg.content = final_answer
            msg.tool_calls = []
        mock_resp.choices = [MagicMock(message=msg)]
        return mock_resp

    return fake_llm


class TestR5E2EMatrix:
    def test_direct_trivial(self, stubbed_agent):
        agent = stubbed_agent
        with patch.object(NallyAgent, "_llm_process") as llm_process:
            result = agent.process("hi")
        assert "Hey" in result or "help" in result.lower()
        assert agent._last_route.strategy == Strategy.DIRECT
        llm_process.assert_not_called()

    def test_react_normal_tool_task(self, stubbed_agent, tmp_path):
        target = tmp_path / "hello.txt"
        target.write_text("hello world", encoding="utf-8")
        agent = stubbed_agent
        fake = _mock_llm_for_react(
            tool_name="read_file",
            tool_args={"file_path": str(target)},
            final_answer="File says hello world.",
        )
        with patch("nally.agent.graph._call_llm_with_retry", side_effect=fake):
            result = agent.process(f"read the file {target}")

        assert "hello world" in result.lower() or "hello" in result.lower()
        # Strategy for a normal read is REACT (SIMPLE -> REACT, not PLAN)
        assert agent._last_route.strategy == Strategy.REACT

    def test_plan_keyword_alone_does_not_force_plan(self, stubbed_agent):
        # "plan this roadmap" contains plan keywords but without COMPLEX signals
        # should not automatically become PLAN via skill alone
        from nally.skills.registry import skill_registry

        skill_registry.load(Path("C:/Users/chuki/Desktop/N.A.L.L.Y/skills"))
        assert "plan" not in skill_registry.find_by_intent("plan this roadmap")

        # Route via task_router directly: simple phrase with plan word but no complexity
        from nally.agent.task_router import route

        decision = route("plan this roadmap")
        # Without COMPLEX classification or strong plan signals, stays REACT
        assert decision.strategy == Strategy.REACT

    def test_planner_failure_falls_back_to_react(self, stubbed_agent):
        agent = stubbed_agent
        # Force COMPLEX classification so router chooses PLAN, but planner LLM fails
        with patch("nally.agent.harness.classify_intent") as mock_classify:
            from nally.agent.harness import Classification, TaskClass

            mock_classify.return_value = Classification(
                task_class=TaskClass.COMPLEX, confidence=0.9, reasoning="test", method="test"
            )
            with patch("nally.agent.llm.llm") as mock_llm:
                # Planner LLM fails -> plan_failed -> should route to REACT
                # REACT LLM then succeeds
                def llm_side_effect(*args, **kwargs):
                    # First call is planner (simple_chat) -> fail
                    # Subsequent calls are REACT llm_call -> succeed via _call_llm_with_retry mock
                    raise Exception("planner down")

                mock_llm.simple_chat.side_effect = llm_side_effect
                # Mock the REACT path's _call_llm_with_retry to succeed
                fake_react = _mock_llm_for_react(
                    tool_name="read_file",
                    tool_args={"file_path": "dummy"},
                    final_answer="Fell back to react and did the thing.",
                )
                with patch("nally.agent.graph._call_llm_with_retry", side_effect=fake_react):
                    # Need to also mock read_file tool to succeed
                    with patch("nally.tools.files.ReadFile.execute", return_value="file content"):
                        result = agent.process("build a complex widget with many steps")

                # If planner failed, we should have gotten a REACT fallback answer, not the dead-end message
                assert "couldn't put a plan together" not in result.lower()
