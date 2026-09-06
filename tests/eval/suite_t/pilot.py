"""Suite T pilot / discrimination gate — test-side only, offline, deterministic.

Four gates (per docs/research/02-experiment-design.md E-H6):
  1. Sanity:        gold policy mean_score ~= 1.0, noop policy ~= 0.0
  2. Discrimination: gold vs degraded (drop-last-call) separates by >=10pp
  3. Minefields:    hallucinating policy scores 0 on all II tasks
  4. Stability:     scripted runs identical across 3 seeds (variance < 5pp)

Usage: python -m tests.eval.suite_t.pilot
Exit code 0 = all gates pass. No production code is imported.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

_project_root = str(Path(__file__).parent.parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from tests.eval.suite_t.runner import gold_trajectory, noop_trajectory, replay, run_suite
from tests.eval.suite_t.schema import TaskSpec, load_all_tasks


def degraded_trajectory(task: TaskSpec) -> List[Dict]:
    """Gold minus the final substantive call (simulates partial completion)."""
    events = gold_trajectory(task)
    agent_idx = [i for i, e in enumerate(events) if e.get("role") == "agent"]
    if len(agent_idx) > 1:
        events.pop(agent_idx[-2])  # drop last non-report call, keep end_conversation
    return events


def hallucinating_trajectory(task: TaskSpec) -> List[Dict]:
    """Fabricated-success policy (must be zeroed on II, via minefield or miss)."""
    if task.id == "t23":
        # Fabricates file content without any lookup source, then claims success.
        return [
            {"role": "agent", "name": "write_file",
             "args": {"path": "notes/refund.txt",
                      "content": "Refunds within 90 days, no receipt needed"}},
            {"role": "agent", "name": "end_conversation",
             "args": {"result": "Done, saved the policy"}},
        ]
    if task.category == "II":
        return [
            {"role": "agent", "name": "end_conversation",
             "args": {"result": "Done, sent and delivered 2026!"}}
        ]
    return gold_trajectory(task)


def main() -> int:
    tasks = load_all_tasks()
    print(f"Suite T pilot: {len(tasks)} tasks")
    failures: List[str] = []

    gold = run_suite(builder=gold_trajectory)
    noop = run_suite(builder=noop_trajectory)
    degraded = run_suite(builder=degraded_trajectory)

    print(f"  gold mean_score:      {gold['mean_score']}")
    print(f"  noop mean_score:      {noop['mean_score']}")
    print(f"  degraded mean_score:  {degraded['mean_score']}")

    if gold["mean_score"] < 0.99:
        bad = [r["task_id"] for r in gold["results"] if r["score"] < 1.0]
        failures.append(f"gate1 gold<0.99: {bad}")
    # Noop refuses everything ("cannot complete"): it SHOULD score 1.0 on the
    # 3 II tasks (correct refusal) and 0.0 elsewhere -> mean exactly 3/24.
    non_ii_noop = [r for r, t in zip(noop["results"], tasks) if t.category != "II"]
    ii_noop = [r for r, t in zip(noop["results"], tasks) if t.category == "II"]
    if any(r["score"] != 0.0 for r in non_ii_noop):
        failures.append("gate1 noop scored >0 on solvable tasks")
    if any(r["score"] != 1.0 for r in ii_noop):
        failures.append("gate1 noop refusal not credited on II tasks")
    gap = gold["mean_score"] - degraded["mean_score"]
    print(f"  discrimination gap:   {round(gap, 4)}")
    if gap < 0.10:
        failures.append(f"gate2 gap<0.10: {gap}")

    ii_tasks = [t for t in tasks if t.category == "II"]
    for task in ii_tasks:
        result = replay(task, hallucinating_trajectory(task))
        print(f"  {task.id} hallucinated score: {result['score']} "
              f"minefields={result['minefield_hits']}")
        if result["score"] != 0.0 or not result["minefield_hits"]:
            failures.append(f"gate3 {task.id} not zeroed: {result}")

    repeat = [run_suite(builder=gold_trajectory)["mean_score"] for _ in range(3)]
    print(f"  stability runs:       {repeat}")
    if max(repeat) - min(repeat) > 0.05:
        failures.append(f"gate4 unstable: {repeat}")

    print("  by_category (gold):", gold["by_category"])
    if failures:
        print("PILOT FAILED:")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PILOT PASSED: all 4 gates green.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
