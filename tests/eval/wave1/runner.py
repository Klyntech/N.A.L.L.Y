"""
Wave 1 — Runner harness (immutable substrate consumer).

Loads 80 task worlds via the four suite loaders, scores via their scorers,
and writes provider x arm results. Never writes to tests/eval/suite_*/tasks
or to any scorer. Provider adapters are injected — the runner itself makes
no LLM calls.

Usage:
  from tests.eval.wave1.runner import Wave1Runner
  runner = Wave1Runner(experiment_id="E-H1", arm="react_sparse", provider="opencode/hy3-free")
  summary = runner.run(adapter=my_adapter)  # adapter: TaskSpec -> trajectory events

Trajectory event model (adapter -> runner):
  [{"role": "agent", "name": <tool>, "args": {...}}, ...]
  The runner replays each trajectory through the suite's SimWorld/PWorld,
  captures snapshots, and delegates scoring to the suite's scorer.

Budget enforcement is OBSERVED, not tuned: the runner tags results that
exceed FIXED_BUDGET but never changes agent behavior to fit.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .config import FROZEN, DEFAULT_TEMPERATURE, EXPERIMENTS
from .schema import TaskResult, ExperimentSummary

# Suite loaders / scorers — READ-ONLY
from tests.eval.suite_t.schema import load_all_tasks as load_t
from tests.eval.suite_p.schema import load_all_tasks as load_p
from tests.eval.suite_a.schema import load_all_tasks as load_a
from tests.eval.suite_c.schema import load_all_tasks as load_c

from tests.eval.suite_t.runner import replay as replay_t
from tests.eval.suite_p.runner import gold_output as gold_p  # not used directly; scorer is via score_task
from tests.eval.suite_t.scorer import score_trajectory as score_t
from tests.eval.suite_p.scorer import score_task as score_p

# Adapter type: given a suite-tagged TaskSpec, produce trajectory events
Adapter = Callable[[Any], List[Dict[str, Any]]]


def _suite_for_task(task_id: str) -> str:
    if task_id.startswith("t"): return "suite_t"
    if task_id.startswith("p"): return "suite_p"
    if task_id.startswith("a"): return "suite_a"
    if task_id.startswith("c"): return "suite_c"
    raise ValueError(task_id)


def _load_all() -> List[Any]:
    tasks: List[Any] = []
    tasks.extend(load_t())
    tasks.extend(load_p())
    tasks.extend(load_a())
    tasks.extend(load_c())
    # deterministic order
    tasks.sort(key=lambda t: t.id)
    return tasks


def _score_one(task: Any, events: List[Dict[str, Any]]) -> Tuple[float, Dict[str, Any]]:
    tid = task.id
    if tid.startswith("t") or tid.startswith("a") or tid.startswith("c"):
        # suite_t/a/c share SimWorld + milestone scorer via replay
        result = replay_t(task, events)
        score = float(result["score"])
        # keep full scorer output for audit
        diag = {k: v for k, v in result.items() if k not in ("score", "log", "final_hash")}
        # attach truncated tool_calls for trajectory log
        tool_calls = [e for e in result.get("log", []) if e.get("role") == "agent"]
        return score, {"scorer": result, "tool_calls": tool_calls, "diag": diag}
    elif tid.startswith("p"):
        # suite_p: events are not replayed; adapter returns structured output
        # For MVP the adapter contract for P is: {"plan": [...]} etc.
        # The runner delegates to score_p via a synthetic adapter output.
        # If adapter produced raw tool events, we treat the first plan-like
        # payload as the output — caller must conform to score_p expectations.
        # Here we assume adapter already returns the structured output dict.
        # Fallback: if events look like tool events, wrap as plan.
        if events and isinstance(events[0], dict) and "action" in events[0]:
            output = {"plan": events}
        elif events and isinstance(events[0], dict) and "name" in events[0]:
            # map suite_t style to suite_p plan style
            output = {"plan": [{"action": e.get("name"), "args": e.get("args", {})} for e in events]}
        else:
            output = events[0] if events else {}
            if not isinstance(output, dict):
                output = {"plan": []}
        # score_p expects task + output dict
        from tests.eval.suite_p.scorer import score_task as _score_p
        scored = _score_p(task, output)
        score = float(scored["score"])
        return score, {"scorer": scored, "tool_calls": [], "diag": scored.get("diagnostics", {})}
    raise ValueError(tid)


class Wave1Runner:
    def __init__(
        self,
        experiment_id: str,
        arm: str,
        provider: str,
        tool_set_mode: Optional[str] = None,
        context_placement: Optional[str] = None,
        temperature: Optional[float] = None,
        results_dir: Optional[Path] = None,
    ):
        if experiment_id not in EXPERIMENTS:
            raise ValueError(f"unknown experiment {experiment_id}")
        self.experiment_id = experiment_id
        self.arm = arm
        self.provider = provider
        self.tool_set_mode = tool_set_mode or FROZEN.default_tool_set
        self.context_placement = context_placement or FROZEN.default_context_placement
        self.temperature = temperature if temperature is not None else FROZEN.default_temperature
        self.results_dir = Path(results_dir) if results_dir else Path("tests/eval/wave1/results")
        # freeze config fingerprint at construction
        self.config_fingerprint = FROZEN.fingerprint()
        self.config_version = FROZEN.version

    def run(
        self,
        adapter: Adapter,
        task_ids: Optional[List[str]] = None,
        write: bool = True,
    ) -> ExperimentSummary:
        start = time.time()
        all_tasks = _load_all()
        if task_ids is not None:
            wanted = set(task_ids)
            tasks = [t for t in all_tasks if t.id in wanted]
        else:
            tasks = all_tasks

        results: List[TaskResult] = []
        for task in tasks:
            t0 = time.time()
            try:
                events = adapter(task)
                if events is None:
                    events = []
                score, audit = _score_one(task, events)
                # Extract scorer fields for TaskResult
                scorer_out = audit.get("scorer", {})
                milestone = float(scorer_out.get("milestone_similarity", score))
                minefields = list(scorer_out.get("minefield_hits", scorer_out.get("minefields", [])))
                diag = audit.get("diag", {})
                tool_calls = audit.get("tool_calls", [])
                wall_ms = (time.time() - t0) * 1000
                # budget observation (never mutates agent)
                budget_used = {
                    "tool_calls": len(tool_calls),
                    "wall_ms": round(wall_ms, 2),
                    "exceeded": len(tool_calls) > FROZEN.budget["MAX_TOOL_CALLS"],
                }
                tr = TaskResult(
                    provider=self.provider,
                    experiment_id=self.experiment_id,
                    arm=self.arm,
                    task_id=task.id,
                    suite=_suite_for_task(task.id),
                    score=round(score, 4),
                    milestone_similarity=round(milestone, 4),
                    minefield_hits=minefields,
                    diagnostics=diag,
                    tool_calls=tool_calls,
                    budget_used=budget_used,
                    temperature=self.temperature,
                    tool_set_mode=self.tool_set_mode,
                    context_placement=self.context_placement,
                    seed=getattr(task, "seed", 0),
                )
                results.append(tr)
            except Exception as e:
                # Never crash the suite; record failure as score 0 with error in diagnostics
                tr = TaskResult(
                    provider=self.provider,
                    experiment_id=self.experiment_id,
                    arm=self.arm,
                    task_id=task.id,
                    suite=_suite_for_task(task.id),
                    score=0.0,
                    milestone_similarity=0.0,
                    minefield_hits=[],
                    diagnostics={"error": str(e)},
                    tool_calls=[],
                    budget_used={"tool_calls": 0, "wall_ms": 0, "exceeded": False},
                    temperature=self.temperature,
                    tool_set_mode=self.tool_set_mode,
                    context_placement=self.context_placement,
                    seed=getattr(task, "seed", 0),
                )
                results.append(tr)

        total = len(results)
        mean = round(sum(r.score for r in results) / total, 4) if total else 0.0
        by_suite: Dict[str, float] = {}
        for suite in ("suite_t", "suite_p", "suite_a", "suite_c"):
            suite_scores = [r.score for r in results if r.suite == suite]
            by_suite[suite] = round(sum(suite_scores) / len(suite_scores), 4) if suite_scores else 0.0
        by_cat: Dict[str, float] = {}
        for cat in ("STC", "MTC", "MUT", "SD", "C", "II", "generation", "optimal", "verification", "execution", "replan", "reuse"):
            cat_scores = [r.score for r, t in zip(results, tasks) if getattr(t, "category", getattr(t, "type", "")) == cat]
            if cat_scores:
                by_cat[cat] = round(sum(cat_scores) / len(cat_scores), 4)

        summary = ExperimentSummary(
            experiment_id=self.experiment_id,
            arm=self.arm,
            provider=self.provider,
            total=total,
            mean_score=mean,
            by_suite=by_suite,
            by_category=by_cat,
            results=results,
        )

        if write:
            self.results_dir.mkdir(parents=True, exist_ok=True)
            fname = f"{self.experiment_id}__{self.arm}__{self.provider.replace('/', '_')}__{self.config_fingerprint}.json"
            with open(self.results_dir / fname, "w") as f:
                json.dump(summary.to_dict(), f, indent=2, sort_keys=True, default=str)

        return summary
