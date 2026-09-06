"""
Wave 1 — Provider adapter interface (stubs; no LLM calls in this commit).

Each adapter implements:  TaskSpec -> List[trajectory events]
The runner replays those events and scores them. Adapters must respect:
- fixed temperature (from config; SC arms may use SC_TEMPERATURE)
- explicit tool_set_mode / context_placement (from runner, never inferred)
- deterministic seed (task.seed + GLOBAL_SEED)

Concrete LLM adapters (opencode/hy3-free, groq/llama-3.3) will live in
tests/eval/wave1/adapters/<provider>.py and will be added in follow-ups.
This file only defines the protocol and deterministic scripted adapters for
local harness self-test (gold / noop / degraded) — no network.
"""

from __future__ import annotations

from typing import Any, Dict, List

from tests.eval.wave1.config import FROZEN

Protocol = Any  # TaskSpec union across suites


def scripted_gold(task: Protocol) -> List[Dict[str, Any]]:
    """Deterministic oracle: replays the task's own gold."""
    # suite_t/a/c: gold_tool_sequence with {name, args}
    if hasattr(task, "gold_tool_sequence") and getattr(task, "gold_tool_sequence"):
        seq = getattr(task, "gold_tool_sequence")
        return [{"role": "agent", "name": s.get("name", s.get("action")), "args": dict(s.get("args", {}))} for s in seq]
    # suite_p: gold is a structured output (plan / verdict / predicted_state)
    gold = getattr(task, "gold", {}) or {}
    if "plan" in gold:
        return [{"action": s.get("action"), "args": s.get("args", {})} for s in gold["plan"]]
    if "verdict" in gold:
        return [dict(gold["verdict"])]
    if "predicted_state" in gold:
        return [{"predicted_state": dict(gold["predicted_state"])}]
    return []


def scripted_noop(task: Protocol) -> List[Dict[str, Any]]:
    """Refusal / empty adapter."""
    if getattr(task, "type", None) in ("verification", "execution"):
        if getattr(task, "type", None) == "verification":
            return [{"executable": True, "goal_reached": True, "first_failure_index": None}]
        return [{"predicted_state": {"dirs": [], "files": {}}}]
    return [{"role": "agent", "name": "end_conversation", "args": {"result": "cannot complete"}}]


def scripted_degraded(task: Protocol) -> List[Dict[str, Any]]:
    """Gold minus last substantive call — tests discrimination."""
    ev = scripted_gold(task)
    # suite_t/a/c: drop last non-report agent event
    if ev and all("role" in e for e in ev):
        idx = [i for i, e in enumerate(ev) if e.get("role") == "agent"]
        if len(idx) > 1:
            ev = list(ev)
            ev.pop(idx[-2])
        return ev
    # suite_p plan: drop last step
    if ev and isinstance(ev[0], dict) and "action" in ev[0]:
        return ev[:-1] if len(ev) > 1 else []
    return ev


# Registry for runner self-test
SCRIPTED = {
    "gold": scripted_gold,
    "noop": scripted_noop,
    "degraded": scripted_degraded,
}
