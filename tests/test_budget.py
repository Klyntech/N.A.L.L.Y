"""Tests for ExecutionBudget — deadline-aware execution limits.

Contract:
  - deadline = started_at (monotonic) + wall_time_limit (authoritative)
  - 80% elapsed → warn_due() True (fires once via warn_fired latch)
  - 100% elapsed → exhausted() True (hard stop)
  - Completion is NEVER decided by the clock (see verification layer tests).
"""

import time

from nally.agent.budget import (
    ExecutionBudget,
    budget_warning_message,
    normalize_start_to_monotonic,
)


def test_deadline_authoritative():
    b = ExecutionBudget(started_at=1000.0, wall_time_limit=300)
    assert b.deadline == 1300.0
    assert b.remaining_time(now=1100.0) == 200.0
    assert b.elapsed(now=1100.0) == 100.0


def test_warn_fires_once_at_threshold():
    b = ExecutionBudget(started_at=1000.0, wall_time_limit=100, warn_threshold=0.8)
    assert b.warn_due(now=1079.9) is False
    assert b.warn_due(now=1080.0) is True
    b.mark_warned()
    assert b.warn_due(now=1090.0) is False  # latch: fires once
    assert b.warn_fired is True


def test_exhausted_at_deadline():
    b = ExecutionBudget(started_at=1000.0, wall_time_limit=100)
    assert b.exhausted(now=1099.9) is False
    assert b.exhausted(now=1100.0) is True


def test_remaining_counts():
    b = ExecutionBudget(max_iterations=10, max_tool_calls=50, max_failures=5)
    assert b.remaining_iterations(7) == 3
    assert b.remaining_tool_calls(48) == 2
    assert b.remaining_failures(5) == 0
    assert b.remaining_iterations(99) == 0


def test_from_state_prefers_deadline():
    state = {
        "deadline": 2000.0,
        "wall_time_budget": 300,
        "budget_warn_fired": True,
        "max_iterations": 10,
    }
    b = ExecutionBudget.from_state(state)
    assert b.started_at == 1700.0
    assert b.warn_fired is True


def test_from_state_legacy_wall_clock_normalized():
    # Legacy time.time() start (~1.7e9) must not produce absurd elapsed on
    # the monotonic clock; age should be preserved (~50s).
    legacy_start = time.time() - 50
    state = {"start_time": legacy_start, "wall_time_budget": 300}
    b = ExecutionBudget.from_state(state)
    assert 40 <= b.elapsed() <= 70


def test_normalize_monotonic_passthrough():
    m = time.monotonic()
    assert normalize_start_to_monotonic(m) == m


def test_budget_warning_message():
    msg = budget_warning_message(36)
    assert "36" in msg
    assert "Prioritize completing" in msg
