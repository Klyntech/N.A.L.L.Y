"""DIRECT vs REACT execution contract.

Locks the post-refactor invariant: the matcher fast path executes DIRECT
with zero LLM/graph involvement, while everything else routes through
TaskRouter and executes via LangGraph (REACT default, PLAN for complex).

Matrix:
  matcher HIT (exact greet / time / date / day) -> DIRECT, no LLM, no graph
  compound input even matching a pattern      -> NOT DIRECT (matcher bypassed)
  matcher MISS (ordinary SIMPLE/KNOWLEDGE)    -> REACT, graph invoked, no planner
  multi-step COMPLEX                          -> PLAN still reachable (coexistence)
"""

import re
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage

from nally.agent.core import NallyAgent
from nally.agent.planner import classify_node, route_after_classify
from nally.agent.router import matcher
from nally.agent.task_router import Strategy, route

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture
def stubbed_agent(monkeypatch):
    """NallyAgent with hermetic memory (no SQLite, no network).

    Constructor + background decay only touch the stubbed store.
    """
    from nally.agent import core as core_mod

    store = MagicMock()
    store.get_user_facts.return_value = "No user facts stored yet."
    store.get_conversation_summaries_text.return_value = ""
    store.get_recent_episodes_text.return_value = ""
    store.load_messages.return_value = []
    monkeypatch.setattr(core_mod, "memory_store", store)
    return core_mod.NallyAgent(session_id="test-direct-react")


@pytest.fixture
def no_llm():
    """Harness classifier forced onto its deterministic regex fallback."""
    with patch("nally.agent.llm.llm") as mock_llm:
        mock_llm.simple_chat.side_effect = Exception("no network in contract tests")
        yield mock_llm


@pytest.fixture
def passthrough_context():
    """Context plumbing is not under test here; routing/dispatch is."""
    mgr = MagicMock()
    mgr.prune.side_effect = lambda messages, **kw: messages
    mgr.compact.side_effect = lambda messages, **kw: messages
    mgr.inject_memories.side_effect = lambda query, messages: messages
    mgr.inject_conversation_history.side_effect = lambda messages: messages
    mgr.estimate_tokens.return_value = 0
    with patch("nally.agent.context.context_manager", mgr):
        yield mgr


# ── Class A: matcher unit contract (no agent) ─────────────────────────────


HIT_CASES = [
    ("hi", r"Hey! How can I help you\?"),
    ("hello", r"Hey! How can I help you\?"),
    ("what time is it", r"The current time is \d{2}:\d{2} [AP]M\."),
    ("today's date", r"Today is \w+, \w+ \d{2}, \d{4}\."),
    ("what day is it", None),  # date vs day handler overlap; either is DIRECT
]

MISS_CASES = [
    "hey, how are you?",
    "Hello there, what can you do?",
    "tell me about time",
    "What's the weather today?",
    "what is photosynthesis?",
]


class TestMatcherContract:
    @pytest.mark.parametrize("text,output_pat", HIT_CASES)
    def test_matcher_hit_returns_callable(self, text, output_pat):
        handler = matcher.match(text)
        assert handler is not None, f"expected matcher HIT for {text!r}"
        result = handler()
        assert isinstance(result, str) and result
        if output_pat is not None:
            assert re.search(output_pat, result), f"unexpected handler output: {result!r}"

    @pytest.mark.parametrize("text", MISS_CASES)
    def test_matcher_miss_returns_none(self, text):
        assert matcher.match(text) is None, f"expected matcher MISS for {text!r}"


# ── Class B: DIRECT executes with zero LLM/graph ──────────────────────────


class TestDirectExecution:
    def test_direct_greet_never_touches_llm_or_graph(self, stubbed_agent, no_llm):
        agent = stubbed_agent
        with (
            patch.object(NallyAgent, "_llm_process") as llm_process,
            patch("nally.agent.graph.run_agent") as run_agent,
        ):
            result = agent.process("hi")

        assert "Hey" in result
        assert agent._last_route is not None
        assert agent._last_route.strategy == Strategy.DIRECT
        assert agent._last_route.method == "rules"
        assert agent._last_route.confidence == 1.0
        llm_process.assert_not_called()
        run_agent.assert_not_called()
        no_llm.simple_chat.assert_not_called()

    def test_direct_time_never_touches_llm_or_graph(self, stubbed_agent, no_llm):
        agent = stubbed_agent
        with (
            patch.object(NallyAgent, "_llm_process") as llm_process,
            patch("nally.agent.graph.run_agent") as run_agent,
        ):
            result = agent.process("what time is it")

        assert re.search(r"The current time is \d{2}:\d{2} [AP]M", result)
        assert agent._last_route.strategy == Strategy.DIRECT
        llm_process.assert_not_called()
        run_agent.assert_not_called()
        no_llm.simple_chat.assert_not_called()


# ── Class C: compound guard bypasses matcher ──────────────────────────────


class TestCompoundGuard:
    def test_compound_request_is_not_direct(self, stubbed_agent):
        """Matcher bypass rule only: compound input must not take the DIRECT
        path. The alternative strategy is the router's business, not this test's."""
        agent = stubbed_agent
        with patch.object(NallyAgent, "_llm_process", return_value="LLM-STUB") as llm_process:
            result = agent.process("what time is it and tell me a joke")

        assert result == "LLM-STUB"
        llm_process.assert_called_once()
        route = getattr(agent, "_last_route", None)
        assert route is None or route.strategy != Strategy.DIRECT


# ── Class D: REACT boundary ───────────────────────────────────────────────


def _classify_state(text, intent="KNOWLEDGE", conf=0.9):
    return {
        "messages": [HumanMessage(content=text)],
        "thread_id": "contract",
        "intent_class": intent,
        "intent_confidence": conf,
    }


class TestReactBoundary:
    def test_simple_miss_routes_react_not_planner(self):
        decision = route("what is photosynthesis?")
        assert decision.strategy == Strategy.REACT

        state = classify_node(_classify_state("what is photosynthesis?"))
        assert state["strategy"] == Strategy.REACT.value
        assert route_after_classify(state) == "llm"

    def test_react_dispatches_to_graph_with_decision(
        self, stubbed_agent, no_llm, passthrough_context
    ):
        agent = stubbed_agent
        with patch("nally.agent.graph.run_agent", return_value="REACT DONE") as run_agent:
            result = agent.process("what is photosynthesis?")

        assert result == "REACT DONE"
        assert agent._last_route.strategy == Strategy.REACT
        # Harness attempted the LLM classifier once, failed closed, and fell
        # back to deterministic regex routing — no LLM output was consumed.
        assert agent._last_route.method == "regex"
        run_agent.assert_called_once()
        supplied = run_agent.call_args.kwargs.get("route_decision")
        assert supplied is not None
        assert supplied.strategy == Strategy.REACT


# ── Class E: PLAN coexistence ─────────────────────────────────────────────


class TestPlanCoexistence:
    def test_complex_still_reaches_planner(self, monkeypatch):
        """The DIRECT/REACT contract must not break automatic planning."""
        import nally.config as cfg

        # route() reads PLAN_ENABLED from nally.config at call time.
        monkeypatch.setattr(cfg, "PLAN_ENABLED", True)

        text = (
            "Build a full web app with backend, migrate the database, "
            "then test it end to end. First inspect the repo, then implement, finally verify."
        )
        state = classify_node(_classify_state(text, intent="COMPLEX"))
        assert state["strategy"] in (Strategy.PLAN.value, Strategy.ENGINEERING.value)
        assert route_after_classify(state) == "planner"
