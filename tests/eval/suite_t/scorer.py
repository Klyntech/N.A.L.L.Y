"""Suite T scorer — test-side only.

Primary correctness score grades STATE TRANSITIONS and OUTCOMES:
  score = milestone_similarity (0..1, weight-normalized) x I(no minefield hit)

Tool precision/recall/F1, turns, and latency are SEPARATE diagnostics and
never enter the primary score (per Phase 3 refinement: a call-heavy agent
must not look better for making more calls).

Trajectory event model (produced by runner.replay or a Phase 4 agent adapter):
  {"role": "agent", "name": <tool>, "args": {...}, "ok": bool, "result": str}
  {"role": "user", "message": str}
World snapshots are captured after every agent event.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from .schema import Milestone, TaskSpec


def _norm(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value, sort_keys=True, default=str)
    return str(value).strip()


def _args_match(expected: Dict[str, Any], actual: Dict[str, Any], mode: str) -> bool:
    for key, want in expected.items():
        if key not in actual:
            return False
        got = _norm(actual[key])
        want_n = _norm(want)
        if mode == "exact":
            if got != want_n:
                return False
        elif want_n.lower() not in got.lower():
            return False
    return True


def _resolve_path(snapshot: Dict[str, Any], path: str) -> Tuple[bool, Any]:
    """Resolve dotted paths with optional [index], e.g. messages[-1].text.

    Dict keys may themselves contain dots (e.g. filenames like
    "notes/refund.txt"), so keys are matched greedily: at each level the
    longest leading segment-run that names a real key wins.
    """
    parts = path.split(".")
    current: Any = snapshot
    i = 0
    while i < len(parts):
        if not isinstance(current, dict):
            return False, None
        matched = False
        for j in range(len(parts), i, -1):
            candidate = ".".join(parts[i:j])
            name, sep, bracket = candidate.partition("[")
            if sep:
                # Only a clean trailing "[int]" is an index; anything else
                # (e.g. "messages[-1].text" from an over-long match) is skipped.
                if not (bracket.endswith("]") and "[" not in bracket):
                    continue
                key = name
            else:
                key = candidate
            if key in current:
                current = current[key]
                if bracket:
                    try:
                        index = int(bracket.rstrip("]"))
                    except ValueError:
                        return False, None
                    if not isinstance(current, list):
                        return False, None
                    try:
                        current = current[index]
                    except IndexError:
                        return False, None
                i = j
                matched = True
                break
        if not matched:
            return False, None
    return True, current


def _value_match(expected: Any, actual: Any, mode: str) -> bool:
    if mode == "exists":
        return actual is not None
    if actual is None:
        return False
    if mode == "exact":
        return _norm(actual) == _norm(expected)
    return _norm(expected).lower() in _norm(actual).lower()


def milestone_event_score(
    milestone: Milestone,
    agent_events: List[Dict[str, Any]],
    snapshots: List[Dict[str, Any]],
) -> float:
    """Best similarity (0..1) of one milestone against the trajectory.

    Respects nothing about ordering here — ordering is enforced by the DAG
    matcher (score_trajectory), which requires milestones to match in an
    order consistent with their `after` edges.
    """
    best = 0.0
    if milestone.kind == "tool_call":
        for event in agent_events:
            if event.get("role") != "agent" or event.get("name") != milestone.tool:
                continue
            if not event.get("ok", True):
                continue  # failed calls never satisfy a milestone
            if _args_match(milestone.args, event.get("args", {}), milestone.arg_match):
                best = 1.0
                break
    else:
        for snap in snapshots:
            found, actual = _resolve_path(snap, milestone.path or "")
            if found and _value_match(milestone.expected, actual, milestone.match):
                best = 1.0
                break
    return best


def _topo_match_order(
    milestones: List[Milestone],
    per_ms_best_index: Dict[str, int],
) -> bool:
    """Check matched indices respect `after` edges (topological order)."""
    index_of = per_ms_best_index
    for ms in milestones:
        if ms.id not in index_of:
            continue
        for dep in ms.after:
            if dep in index_of and index_of[dep] > index_of[ms.id]:
                return False
    return True


def score_trajectory(
    task: TaskSpec,
    agent_events: List[Dict[str, Any]],
    snapshots: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Score one trajectory. Returns primary score + diagnostics."""
    # Minefields first: any hit zeroes the task.
    minefield_hits = []
    for mf in task.minefields:
        if milestone_event_score(mf, agent_events, snapshots) > 0:
            minefield_hits.append(mf.id)

    # Milestone similarities, matched greedily in DAG order with positions.
    ordered = _order_for_matching(task.milestones)
    weights = sum(m.weight for m in task.milestones) or 1.0
    earned = 0.0
    detail = {}
    matched_positions: Dict[str, int] = {}
    for ms in ordered:
        sim = milestone_event_score(ms, agent_events, snapshots)
        detail[ms.id] = sim
        if sim > 0:
            matched_positions[ms.id] = _first_match_position(ms, agent_events, snapshots)
            earned += sim * ms.weight

    milestone_similarity = earned / weights
    if not _topo_match_order(task.milestones, matched_positions):
        milestone_similarity = 0.0
        detail["_order_violation"] = True

    primary = 0.0 if minefield_hits else round(milestone_similarity, 4)

    gold = task.gold_tool_sequence
    agent_calls = [
        (e.get("name"), json.dumps(e.get("args", {}), sort_keys=True, default=str))
        for e in agent_events if e.get("role") == "agent" and e.get("ok", True)
    ]
    gold_norm = [
        (g.get("name"), json.dumps(g.get("args", {}), sort_keys=True, default=str))
        for g in gold
    ]
    matched = 0
    remaining = list(agent_calls)
    for g in gold_norm:
        if g in remaining:
            remaining.remove(g)
            matched += 1
    precision = matched / len(agent_calls) if agent_calls else 0.0
    recall = matched / len(gold_norm) if gold_norm else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0

    return {
        "task_id": task.id,
        "score": primary,  # PRIMARY correctness: milestones x minefields
        "milestone_similarity": round(milestone_similarity, 4),
        "minefield_hits": minefield_hits,
        "milestones": detail,
        # diagnostics (never mixed into score)
        "tool_precision": round(precision, 4),
        "tool_recall": round(recall, 4),
        "tool_f1": round(f1, 4),
        "turns": len(agent_calls),
    }


def _order_for_matching(milestones: List[Milestone]) -> List[Milestone]:
    ordered, visited = [], set()

    def visit(ms: Milestone) -> None:
        if ms.id in visited:
            return
        for dep in ms.after:
            parent = next((m for m in milestones if m.id == dep), None)
            if parent is not None:
                visit(parent)
        visited.add(ms.id)
        ordered.append(ms)

    for ms in milestones:
        visit(ms)
    return ordered


def _first_match_position(
    ms: Milestone,
    agent_events: List[Dict[str, Any]],
    snapshots: List[Dict[str, Any]],
) -> int:
    if ms.kind == "tool_call":
        for i, event in enumerate(agent_events):
            if event.get("role") != "agent" or event.get("name") != ms.tool:
                continue
            if event.get("ok", True) and _args_match(
                ms.args, event.get("args", {}), ms.arg_match
            ):
                return i
        return len(agent_events)
    for i, snap in enumerate(snapshots):
        found, actual = _resolve_path(snap, ms.path or "")
        if found and _value_match(ms.expected, actual, ms.match):
            return i
    return len(snapshots)
