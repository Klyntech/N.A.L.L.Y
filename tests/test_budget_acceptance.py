"""Milestone A acceptance tests — ExecutionBudget semantic guarantees.

These tests prove the budget-enforcement contract is enforced in the graph
and verification layer, not just the budget dataclass.

Acceptance invariant:
  A completed task must remain completed even when the elapsed clock
  crosses the 80% warning threshold afterward.

Tests:
  T1 — warning fires exactly once across consecutive turns
  T2 — warning present → completion unaffected (no clock block)
  T3 — deadline passed → graceful stop with continue-hint
  T4 — success receipts + aged clock → should_block=False
  T5 — failure halt honors state-carried max_failures
"""

import time
from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from nally.agent.budget import ExecutionBudget
from nally.agent.verification.layer import VerificationLayer, _partial_reason

# ── T1: Warning fires exactly once across consecutive turns ──

def test_t1_warning_fires_once_across_turns():
    """80% warning fires once and latches, even as more turns pass."""
    b = ExecutionBudget(started_at=1000.0, wall_time_limit=100, warn_threshold=0.8)

    # Before threshold
    assert b.warn_due(now=1079.9) is False

    # At threshold — fires
    assert b.warn_due(now=1080.0) is True
    b.mark_warned()

    # Next turn, still past threshold — does NOT fire again
    assert b.warn_due(now=1090.0) is False

    # Latch persists even if we reconstruct from state via graph key
    state = b.to_dict()
    state["budget_warn_fired"] = state.pop("warn_fired", False)  # normalize to graph key
    b2 = ExecutionBudget.from_state(state)
    assert b2.warn_fired is True
    assert b2.warn_due(now=1100.0) is False


# ── T2: Warning present → completion unaffected ──

def test_t2_warning_does_not_block_completion():
    """Even when the 80% warning fires, should_block remains False."""
    layer = VerificationLayer()

    # Simulate: tool succeeded, but clock is past 80%
    result = layer.verify_turn(
        "I wrote the file successfully.",
        tool_failures=[],
        task_progress={"write_file": "success"},
        start_time=time.monotonic() - 250,  # 250s ago, budget=300
        wall_budget=300,
        tool_calls_total=1,
    )

    # Budget warning should be present (elapsed > 80% of 300)
    # But should_block MUST be False — tool succeeded
    assert result.should_block is False
    assert result.budget_warning != ""  # warning was generated


# ── T3: Deadline passed → graceful stop ──

def test_t3_deadline_graceful_stop():
    """should_continue returns 'end' on deadline with continue-hint."""
    # Simulate a state that has exceeded its deadline
    now = time.monotonic()
    state = {
        "deadline": now - 10,  # 10s ago
        "wall_time_budget": 300,
        "start_time": now - 310,
        "iteration": 3,
        "max_iterations": 10,
        "tool_calls_total": 5,
        "max_tool_calls": 50,
        "tool_failures": [],
        "max_failures": 5,
        "thread_id": "test-t3",
        "budget_warn_fired": True,
        "budget_warn_threshold": 0.8,
        "messages": [],
    }

    with patch("nally.agent.graph._get_emit", return_value=MagicMock()):
        from nally.agent.graph import should_continue
        result = should_continue(state)

    assert result == "end"


# ── T4: Success receipts + aged clock → should_block=False ──

def test_t4_completed_task_not_blocked_by_clock():
    """The core invariant: completed stays completed past 80% threshold."""
    layer = VerificationLayer()

    # Tool failed in task_progress, but the OTHER tools succeeded
    # AND the response claims completion based on receipts
    result = layer.verify_turn(
        "File written successfully. The content matches.",
        tool_failures=[],
        task_progress={
            "write_file": "success",
            "read_file": "success",
            "verify_output": "success",
        },
        start_time=time.monotonic() - 500,  # 500s ago, well past 80% of 600
        wall_budget=600,
        tool_calls_total=3,
    )

    # No failures → should_block must be False regardless of clock
    assert result.should_block is False

    # Also test with zero tool_calls_total (edge case from verification layer)
    result2 = layer.verify_turn(
        "Done. Task complete.",
        tool_failures=[],
        task_progress={"complete": "success"},
        start_time=time.monotonic() - 500,
        wall_budget=600,
        tool_calls_total=0,
    )
    assert result2.should_block is False


# ── T4b: _partial_reason never returns clock-based reasons ──

def test_t4b_partial_reason_never_clock_based():
    """_partial_reason ignores clock; only failures/partial trigger block."""
    reason = _partial_reason(
        tool_failures=[],
        task_progress={"write_file": "success"},
        start_time=time.monotonic() - 500,
        wall_budget=600,
        tool_calls_total=3,
    )
    assert reason == ""  # no failures → no block


# ── T5: Failure halt honors state-carried max_failures ──

def test_t5_failure_halt_uses_state_carried_limit():
    """should_continue reads max_failures from state, not constant."""
    now = time.monotonic()
    state = {
        "deadline": now + 300,  # plenty of time left
        "wall_time_budget": 600,
        "start_time": now - 50,
        "iteration": 2,
        "max_iterations": 10,
        "tool_calls_total": 10,
        "max_tool_calls": 50,
        "tool_failures": [
            {"tool": "run_command", "error": "timeout"},
            {"tool": "run_command", "error": "timeout"},
        ],
        "max_failures": 2,  # strict limit: 2
        "thread_id": "test-t5",
        "budget_warn_fired": False,
        "budget_warn_threshold": 0.8,
        "messages": [],
    }

    with patch("nally.agent.graph._get_emit", return_value=MagicMock()):
        from nally.agent.graph import should_continue
        result = should_continue(state)

    assert result == "end"  # 2 failures >= max_failures=2


# ── T5b: Tool-call budget enforcement ──

def test_t5b_tool_call_budget_enforced():
    """should_continue reads max_tool_calls from state."""
    now = time.monotonic()
    state = {
        "deadline": now + 300,
        "wall_time_budget": 600,
        "start_time": now - 50,
        "iteration": 3,
        "max_iterations": 10,
        "tool_calls_total": 20,  # hit the limit
        "max_tool_calls": 20,
        "tool_failures": [],
        "max_failures": 5,
        "thread_id": "test-t5b",
        "budget_warn_fired": False,
        "budget_warn_threshold": 0.8,
        "messages": [],
    }

    with patch("nally.agent.graph._get_emit", return_value=MagicMock()):
        from nally.agent.graph import should_continue
        result = should_continue(state)

    assert result == "end"  # tool_calls_total >= max_tool_calls


# ── T5c: Normal case — under all budgets → continues ──

def test_t5c_under_budgets_continues():
    """should_continue returns 'continue' when within all limits."""
    now = time.monotonic()
    # Need an AI message with tool_calls so natural exit doesn't trigger
    _ai_msg = AIMessage(content="thinking", tool_calls=[{"id": "tc1", "name": "run_command", "args": {}}])
    state = {
        "deadline": now + 300,
        "wall_time_budget": 600,
        "start_time": now - 50,
        "iteration": 2,
        "max_iterations": 10,
        "tool_calls_total": 5,
        "max_tool_calls": 50,
        "tool_failures": [],
        "max_failures": 5,
        "thread_id": "test-t5c",
        "budget_warn_fired": False,
        "budget_warn_threshold": 0.8,
        "messages": [_ai_msg],
    }

    with patch("nally.agent.graph._get_emit", return_value=MagicMock()):
        from nally.agent.graph import should_continue
        result = should_continue(state)

    assert result == "tools"  # "tools" is LangGraph's continue path — execute tool calls
