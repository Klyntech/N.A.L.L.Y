"""ExecutionBudget — single source of truth for execution limits.

Decouples three concepts that were previously tangled:

  1. What kind of task is this?      → TaskClass (harness)
  2. How should I execute it?        → Strategy (TaskRouter)
  3. How much may execution spend?   → ExecutionBudget (this module)

Semantic rule:
  - 80% elapsed  → budget WARNING (agent-visible, fires once, never blocks)
  - 100% elapsed → budget EXHAUSTED (graceful stop, checkpoint + resume)
  - Completion is determined by explicit graph state (no tool calls left,
    plan done, abort), never by the clock.

Timing uses time.monotonic() (elapsed-duration clock, immune to wall-clock
jumps) instead of time.time(). The legacy ``start_time`` / ``wall_time_budget``
fields are kept as compat shims; ``deadline`` is authoritative:

    deadline = started_at_monotonic + wall_time_limit
    remaining = deadline - monotonic()
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


def now_monotonic() -> float:
    """Current monotonic clock reading (seconds)."""
    return time.monotonic()


# Wall-clock timestamps (time.time(), ~1.7e9) vs monotonic readings (~1e4-1e6)
# must not be mixed. Legacy state/tests may still carry time.time() values;
# detect and normalize so elapsed math stays correct across the migration.
_WALL_CLOCK_FLOOR = 1_000_000_000.0


def normalize_start_to_monotonic(start_time: float) -> float:
    """Map a legacy wall-clock start_time onto the monotonic clock.

    If ``start_time`` looks like a wall-clock timestamp (>1e9), convert it
    to the monotonic reading with the same elapsed age:
    monotonic_now - (wall_now - start). Otherwise return as-is.
    Returns now_monotonic() for falsy input.
    """
    try:
        start = float(start_time or 0.0)
    except (TypeError, ValueError):
        return now_monotonic()
    if not start:
        return now_monotonic()
    if start >= _WALL_CLOCK_FLOOR:
        try:
            age = max(0.0, time.time() - start)
        except Exception:
            age = 0.0
        return now_monotonic() - age
    return start


@dataclass
class ExecutionBudget:
    """Central execution-budget tracker for one agent turn.

    Attributes:
        started_at: monotonic timestamp when the turn started.
        wall_time_limit: total wall-clock budget in seconds.
        warn_threshold: fraction of budget at which a warning fires (0.8).
        max_iterations: max LangGraph iterations for the turn.
        max_tool_calls: max tool calls for the turn.
        max_failures: max failed tool calls before halting.
        warn_fired: whether the 80% warning has already fired (fires once).
    """

    started_at: float = field(default_factory=now_monotonic)
    wall_time_limit: int = 300
    warn_threshold: float = 0.8
    max_iterations: int = 30
    max_tool_calls: int = 50
    max_failures: int = 5
    warn_fired: bool = False

    # ── Deadline (authoritative) ──

    @property
    def deadline(self) -> float:
        """Monotonic deadline: started_at + wall_time_limit."""
        return self.started_at + float(self.wall_time_limit or 0)

    def elapsed(self, now: float | None = None) -> float:
        """Seconds elapsed since start (never negative)."""
        current = now if now is not None else time.monotonic()
        return max(0.0, current - self.started_at)

    def remaining_time(self, now: float | None = None) -> float:
        """Seconds remaining until the deadline (never negative)."""
        current = now if now is not None else time.monotonic()
        return max(0.0, self.deadline - current)

    # ── Warning vs exhaustion ──

    def warn_due(self, now: float | None = None) -> bool:
        """True once elapsed crosses warn_threshold * limit (and not yet fired)."""
        if self.warn_fired:
            return False
        limit = float(self.wall_time_limit or 0)
        if limit <= 0:
            return False
        return self.elapsed(now) >= limit * float(self.warn_threshold or 0.8)

    def mark_warned(self) -> None:
        """Record that the one-shot warning has fired."""
        self.warn_fired = True

    def exhausted(self, now: float | None = None) -> bool:
        """True when the deadline has passed (hard stop)."""
        limit = float(self.wall_time_limit or 0)
        if limit <= 0:
            return False
        current = now if now is not None else time.monotonic()
        return current >= self.deadline

    # ── Remaining counts (iterations / tools / failures) ──

    def remaining_iterations(self, iteration: int) -> int:
        return max(0, int(self.max_iterations or 0) - int(iteration or 0))

    def remaining_tool_calls(self, tool_calls_total: int) -> int:
        return max(0, int(self.max_tool_calls or 0) - int(tool_calls_total or 0))

    def remaining_failures(self, failure_count: int) -> int:
        return max(0, int(self.max_failures or 0) - int(failure_count or 0))

    # ── Serialisation (for graph state compat) ──

    def to_dict(self) -> dict:
        return {
            "started_at": self.started_at,
            "wall_time_limit": self.wall_time_limit,
            "warn_threshold": self.warn_threshold,
            "max_iterations": self.max_iterations,
            "max_tool_calls": self.max_tool_calls,
            "max_failures": self.max_failures,
            "warn_fired": self.warn_fired,
            "deadline": self.deadline,
        }

    @classmethod
    def from_state(
        cls,
        state: dict,
        *,
        wall_time_limit: int = 300,
        warn_threshold: float = 0.8,
        max_iterations: int = 30,
        max_tool_calls: int = 50,
        max_failures: int = 5,
    ) -> "ExecutionBudget":
        """Rebuild a budget view from LangGraph state.

        Prefers the authoritative ``deadline`` field when present; falls back
        to ``start_time`` (treated as monotonic post-migration) + budget.
        """
        warn_fired = bool(state.get("budget_warn_fired", False))
        deadline = state.get("deadline", 0) or 0.0
        limit = int(state.get("wall_time_budget", 0) or wall_time_limit or 0)
        if deadline:
            raw_deadline = float(deadline)
            if raw_deadline >= _WALL_CLOCK_FLOOR:
                # Legacy wall-clock deadline — normalize to monotonic.
                try:
                    remaining = max(0.0, raw_deadline - time.time())
                except Exception:
                    remaining = 0.0
                started_at = now_monotonic() - max(0.0, float(limit) - remaining)
            else:
                started_at = raw_deadline - float(limit)
        else:
            started_at = normalize_start_to_monotonic(state.get("start_time", 0) or 0.0)
        return cls(
            started_at=started_at,
            wall_time_limit=limit,
            warn_threshold=float(
                state.get("budget_warn_threshold", 0) or warn_threshold or 0.8
            ),
            max_iterations=int(state.get("max_iterations", 0) or max_iterations),
            max_tool_calls=max_tool_calls,
            max_failures=max_failures,
            warn_fired=warn_fired,
        )


def budget_warning_message(remaining_seconds: float) -> str:
    """Agent-visible (LLM) budget nudge — internal, not user-facing."""
    secs = max(0, int(remaining_seconds))
    return (
        f"You have approximately {secs} seconds of execution budget remaining. "
        "Prioritize completing the task with the information gathered so far; "
        "avoid starting new exploration unless essential."
    )
