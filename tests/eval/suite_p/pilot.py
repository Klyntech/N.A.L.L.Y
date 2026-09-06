"""Suite P pilot — test-side only, deterministic.

Four gates (mirrors Suite T bar):
  1. Sanity:        gold policy scores 1.0 per task.
  2. Discrimination: degraded / invalid / non-optimal separates by >=10pp.
  3. Mine-ish:      obfuscated twin preserves validation verdict.
  4. Stability:     three identical runs identical scores.

Usage: python -m tests.eval.suite_p.pilot
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

_project_root = str(Path(__file__).parent.parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from tests.eval.suite_p.runner import degraded_output, gold_output, noop_output, run_suite
from tests.eval.suite_p.schema import load_all_tasks
from tests.eval.suite_p.scorer import score_task


def hallucinating_plan(task) -> Dict:
    """Fabricated verdict that is *opposite* of validator truth (must score 0)."""
    from tests.eval.suite_p.world import validate_plan
    if task.type in ("generation", "optimal", "replan", "reuse"):
        return {"plan": []}
    if task.type == "verification":
        rep = validate_plan(task.initial_state, task.candidate_plan, task.goal, task.costs)
        truth_exec = bool(rep["executable"])
        # flip verdict: if truth says executable, claim failure, and vice versa
        if truth_exec:
            return {"executable": False, "goal_reached": False, "first_failure_index": 0}
        return {"executable": True, "goal_reached": True, "first_failure_index": None}
    if task.type == "execution":
        # Invert every expected predicate so not a single probe matches, yielding 0.0.
        # For execution tasks partial credit is inherent, so we force a fully-wrong
        # predicted snapshot instead of an empty one.
        rep = validate_plan(task.initial_state, task.start_and_actions["actions"], task.goal, task.costs)
        truth = rep["snapshots"][-1]
        probes = task.gold.get("expected_predicates", task.goal)
        flipped: Dict = {"dirs": [], "files": {}}
        # Start from truth then flip each probe
        flipped = {"dirs": list(truth["dirs"]), "files": dict(truth["files"])}
        for pred in probes:
            if "exists" in pred:
                flipped["files"].pop(pred["exists"], None)
                # ensure probe now false by absence; if it was already absent, make it present to flip
                if pred["exists"] not in truth["files"]:
                    flipped["files"][pred["exists"]] = "__WRONG__"
            elif "absent" in pred:
                flipped["files"][pred["absent"]] = "__WRONG__"
                if pred["absent"] in flipped["dirs"]:
                    flipped["dirs"].remove(pred["absent"])
            elif "dir_exists" in pred:
                if pred["dir_exists"] in flipped["dirs"]:
                    flipped["dirs"].remove(pred["dir_exists"])
                else:
                    flipped["dirs"].append(pred["dir_exists"])
            elif "contains" in pred:
                path = pred["contains"][0]
                flipped["files"].pop(path, None)
        return {"predicted_state": flipped}
    raise ValueError(task.type)


def main() -> int:
    tasks = load_all_tasks()
    print(f"Suite P pilot: {len(tasks)} tasks")
    failures: List[str] = []

    gold = run_suite(builder=gold_output)
    noop = run_suite(builder=noop_output)
    degraded = run_suite(builder=degraded_output)

    print(f"  gold mean_score:     {gold['mean_score']}")
    print(f"  noop mean_score:     {noop['mean_score']}")
    print(f"  degraded mean_score: {degraded['mean_score']}")

    bad_gold = [r["task_id"] for r in gold["results"] if r["score"] < 1.0]
    if bad_gold:
        failures.append(f"gate1 gold not 1.0: {bad_gold}")

    gap = gold["mean_score"] - degraded["mean_score"]
    print(f"  discrimination gap:  {round(gap, 4)}")
    if gap < 0.10:
        failures.append(f"gate2 gap<0.10: {gap}")
    # Non-trivial: noop must be distinguishable from gold
    if gold["mean_score"] - noop["mean_score"] < 0.20:
        failures.append(f"gate2 gold-noop gap<0.20: {gold['mean_score']-noop['mean_score']}")

    # Twins must validate identically to their base (presentation-only difference)
    twin_pairs = [(t.id, t.obfuscation_of) for t in tasks if t.obfuscation_of]
    for twin_id, base_id in twin_pairs:
        twin = next(t for t in tasks if t.id == twin_id)
        base = next(t for t in tasks if t.id == base_id)
        twin_score = score_task(twin, gold_output(twin))["score"]
        base_score = score_task(base, gold_output(base))["score"]
        if twin_score != base_score:
            failures.append(f"gate3 twin {twin_id}->{base_id}: {twin_score} != {base_score}")
        # also hallucinating must score 0 on both
        if score_task(twin, hallucinating_plan(twin))["score"] != 0.0:
            failures.append(f"gate3 twin {twin_id} hallucination not zeroed")

    repeat = [run_suite(builder=gold_output)["mean_score"] for _ in range(3)]
    print(f"  stability runs:      {repeat}")
    if max(repeat) - min(repeat) > 1e-9:
        failures.append(f"gate4 unstable: {repeat}")

    # Per-type sanity
    for task in tasks:
        gs = score_task(task, gold_output(task))["score"]
        if gs != 1.0:
            failures.append(f"gate1 {task.id} gold {gs}")

    if failures:
        print("PILOT FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PILOT PASSED: all 4 gates green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
