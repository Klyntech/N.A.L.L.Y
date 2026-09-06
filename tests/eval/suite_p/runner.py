"""Suite P runner — test-side only, deterministic, offline.

Replays oracle / degraded / blind policies against the mechanical validator.
An agent adapter for Phase 4 provides the same `plan` / verification verdict
/ predicted-state objects; the runner never imports production agent code.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

_project_root = str(Path(__file__).parent.parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from tests.eval.suite_p.schema import TaskSpec, load_all_tasks
from tests.eval.suite_p.scorer import score_task

AgentOutputBuilder = Callable[[TaskSpec], Dict[str, Any]]


def gold_output(task: TaskSpec) -> Dict[str, Any]:
    if task.type in ("generation", "optimal", "replan", "reuse"):
        return {"plan": list(task.gold.get("plan", []))}
    if task.type == "verification":
        return dict(task.gold.get("verdict", {}))
    if task.type == "execution":
        return {"predicted_state": dict(task.gold.get("predicted_state", {}))}
    raise ValueError(task.type)


def noop_output(task: TaskSpec) -> Dict[str, Any]:
    if task.type in ("generation", "optimal", "replan", "reuse"):
        return {"plan": []}
    if task.type == "verification":
        return {"executable": True, "goal_reached": True, "first_failure_index": None}
    if task.type == "execution":
        return {"predicted_state": {"dirs": [], "files": {}}}
    raise ValueError(task.type)


def degraded_output(task: TaskSpec) -> Dict[str, Any]:
    """Drops last substantive step (tests dependency sensitivity)."""
    base = gold_output(task)
    if task.type in ("generation", "optimal", "replan", "reuse") and base.get("plan"):
        base = dict(base)
        base["plan"] = list(base["plan"][:-1])
    elif task.type == "verification":
        base = {"executable": True, "goal_reached": True, "first_failure_index": None}
    elif task.type == "execution":
        # flip one predicate probe
        state = dict(base.get("predicted_state", {"dirs": [], "files": {}}))
        state["files"] = dict(state.get("files", {}))
        if state["files"]:
            key = next(iter(state["files"]))
            state["files"][key] = "__WRONG__"
        base = {"predicted_state": state}
    return base


def run_task(task: TaskSpec, builder: AgentOutputBuilder = gold_output) -> Dict[str, Any]:
    start = time.time()
    out = builder(task)
    scored = score_task(task, out)
    scored["latency_ms"] = round((time.time() - start) * 1000, 2)
    scored["task_id"] = task.id
    return scored


def run_suite(
    tasks_dir: Optional[Path] = None,
    builder: AgentOutputBuilder = gold_output,
) -> Dict[str, Any]:
    tasks = load_all_tasks(tasks_dir)
    results = [run_task(t, builder) for t in tasks]
    mean = sum(r["score"] for r in results) / len(results) if results else 0.0
    return {
        "total": len(results),
        "mean_score": round(mean, 4),
        "results": results,
    }
