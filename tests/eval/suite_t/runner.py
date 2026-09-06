"""Suite T runner — test-side only, deterministic, offline.

Replays scripted trajectories (gold / degraded / adapter-provided) through
SimWorld with a fixed seed, captures world snapshots per agent turn,
interleaves scripted MUT user messages, and scores via scorer.py.

Phase 4 agents plug in by providing a trajectory-builder callable with the
same event model — the runner never imports production agent code itself.
Budget caps from nally/config.py are READ here only to tag runs that would
have exceeded them (observed, not enforced by tuning).
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .schema import TaskSpec, load_all_tasks, load_task
from .scorer import score_trajectory
from .world import SimWorld

TrajectoryBuilder = Callable[[TaskSpec], List[Dict[str, Any]]]


def gold_trajectory(task: TaskSpec) -> List[Dict[str, Any]]:
    """Replay the task's own gold_tool_sequence, interleaving scripted users."""
    events: List[Dict[str, Any]] = []
    user_turns = sorted(task.user_turns, key=lambda u: u.get("after_agent_turn", 0))
    for user in [u for u in user_turns if u.get("after_agent_turn", 0) <= 0]:
        events.append({"role": "user", "message": user.get("message", "")})
    agent_done = 0
    for step in task.gold_tool_sequence:
        events.append({"role": "agent", "name": step["name"], "args": dict(step.get("args", {}))})
        agent_done += 1
        for user in [u for u in user_turns if u.get("after_agent_turn", 0) == agent_done]:
            events.append({"role": "user", "message": user.get("message", "")})
    return events


def noop_trajectory(task: TaskSpec) -> List[Dict[str, Any]]:
    return [{"role": "agent", "name": "end_conversation", "args": {"result": "cannot complete"}}]


def replay(task: TaskSpec, events: List[Dict[str, Any]]) -> Dict[str, Any]:
    world = SimWorld(task.initial_state)
    agent_events: List[Dict[str, Any]] = []
    snapshots: List[Dict[str, Any]] = [world.snapshot()]
    log: List[Dict[str, Any]] = []
    start = time.time()
    for event in events:
        if event.get("role") == "user":
            log.append({"role": "user", "message": event.get("message", "")})
            continue
        name, args = event.get("name", ""), dict(event.get("args", {}))
        ok, result = world.apply_tool(name, args)
        record = {"role": "agent", "name": name, "args": args, "ok": ok, "result": result}
        agent_events.append(record)
        log.append(record)
        snapshots.append(world.snapshot())
    latency_ms = (time.time() - start) * 1000
    scored = score_trajectory(task, agent_events, snapshots)
    scored["latency_ms"] = round(latency_ms, 2)
    scored["final_hash"] = world.snapshot_hash()
    scored["log"] = log
    return scored


def run_task(task: TaskSpec, builder: TrajectoryBuilder = gold_trajectory) -> Dict[str, Any]:
    return replay(task, builder(task))


def run_suite(
    tasks_dir: Optional[Path] = None,
    builder: TrajectoryBuilder = gold_trajectory,
) -> Dict[str, Any]:
    tasks = load_all_tasks(tasks_dir)
    results = [run_task(t, builder) for t in tasks]
    mean_score = sum(r["score"] for r in results) / len(results) if results else 0.0
    by_category: Dict[str, List[float]] = {}
    for task, result in zip(tasks, results):
        by_category.setdefault(task.category, []).append(result["score"])
    return {
        "total": len(results),
        "mean_score": round(mean_score, 4),
        "by_category": {k: round(sum(v) / len(v), 4) for k, v in by_category.items()},
        "results": results,
    }
