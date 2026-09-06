"""Suite P scorer — test-side only.

Scores STATE TRANSITIONS and OUTCOMES, never prose.

For execution-bearing types (generation, optimal, replan, reuse):
  validator(plan) -> executable?, goal_reached?, first_failure, cost.
  scorer unpacks subgoals (dependency DAG) + terminal goal + optimality.
For verification:
  binary: predicted verdict (executable? goal_reached? + first_failure)
  matches validator ground truth.
For execution-prediction:
  predicts the next-world predicates after a given action sequence.

A plan that writes nicely but fails the validator never scores.
"""

from __future__ import annotations

from typing import Any, Dict, List, Tuple

from .schema import TaskSpec
from .world import predicate_holds, validate_plan, optimal_cost, PWorld


def _subgoal_scores(snapshots: List[Dict[str, Any]], subgoals) -> Tuple[float, Dict[str, float], bool]:
    """Weight-normalized subgoal coverage + DAG order check."""
    if not subgoals:
        return 1.0, {}, True
    total = sum(s.weight for s in subgoals) or 1.0
    # first snapshot index where each subgoal predicate becomes true (or None)
    # Ignore initial snapshot (idx 0) so vacuously-true predicates at start
    # (e.g. absent) do not count — the plan must cause the subgoal after deps.
    first_hit: Dict[str, int] = {}
    for idx, snap in enumerate(snapshots):
        if idx == 0:
            continue
        for sg in subgoals:
            if sg.id not in first_hit and predicate_holds(snap, sg.predicate):
                first_hit[sg.id] = idx
    earned = sum(s.weight for s in subgoals if s.id in first_hit)
    # DAG order: every 'after' must hit no later than dependent (equal allowed
    # when both become true in the same atomic step, e.g. file existence +
    # its content after a single write).
    order_ok = True
    for sg in subgoals:
        if sg.id not in first_hit:
            continue
        for dep in sg.after:
            if dep not in first_hit or first_hit[dep] > first_hit[sg.id]:
                order_ok = False
    detail = {sg.id: 1.0 if sg.id in first_hit else 0.0 for sg in subgoals}
    return earned / total, detail, order_ok


def score_execution_task(task: TaskSpec, plan: List[Dict[str, Any]]) -> Dict[str, Any]:
    rep = validate_plan(task.initial_state, plan, task.goal, task.costs)
    order = task.subgoals
    sub_coverage, sub_detail, order_ok = _subgoal_scores(rep["snapshots"], order)
    terminal = 1.0 if rep["goal_reached"] else 0.0
    executable = 1.0 if rep["executable"] else 0.0
    # optimality (only for type 'optimal'; otherwise 1.0 / 0.0 on goal)
    optimality = 1.0
    if task.type == "optimal" and rep["goal_reached"] and rep["executable"]:
        try:
            opt = optimal_cost(task.initial_state, task.goal, task.costs, [plan, task.gold.get("plan", [])])
            optimality = 1.0 if rep["cost"] <= opt + 1e-9 else 0.0
        except Exception:
            optimality = 0.0
    primary = 0.0
    if task.type == "optimal":
        primary = executable * terminal * optimality
    else:
        # generation / replan / reuse: terminal AND executable AND subgoal coverage + order
        # score is product so skipped prereqs or invalid steps cannot be papered over
        primary = executable * terminal
        if order:
            primary *= sub_coverage * (1.0 if order_ok else 0.0)
    # diagnostics (never folded into primary beyond the factors above)
    diag = {
        "executable": bool(rep["executable"]),
        "goal_reached": bool(rep["goal_reached"]),
        "first_failure": rep["first_failure"],
        "missing_goals": rep["missing_goals"],
        "cost": rep["cost"],
        "subgoal_coverage": round(sub_coverage, 4),
        "subgoal_detail": sub_detail,
        "order_ok": order_ok,
        "optimality": optimality,
    }
    return {"score": round(primary, 4), "diagnostics": diag, "milestone_similarity": round(sub_coverage, 4)}


def score_verification_task(task: TaskSpec, prediction: Dict[str, Any]) -> Dict[str, Any]:
    """prediction = {executable: bool, goal_reached: bool, first_failure_index: int|None}."""
    truth = validate_plan(task.initial_state, task.candidate_plan, task.goal, task.costs)
    truth_exec = bool(truth["executable"])
    truth_goal = bool(truth["goal_reached"]) if truth_exec else False
    truth_idx = None if truth_exec else truth["first_failure"]["index"]
    pred_exec = bool(prediction.get("executable"))
    pred_goal = bool(prediction.get("goal_reached")) if pred_exec else False
    pred_idx = prediction.get("first_failure_index")
    exec_ok = pred_exec == truth_exec
    goal_ok = pred_goal == truth_goal or not truth_exec  # goal only defined when executable
    idx_ok = (pred_idx == truth_idx) if not truth_exec else True
    primary = 1.0 if (exec_ok and goal_ok and idx_ok) else 0.0
    return {
        "score": primary,
        "diagnostics": {
            "truth": {"executable": truth_exec, "goal_reached": truth_goal, "first_failure_index": truth_idx,
                      "missing": truth["first_failure"], "missing_goals": truth["missing_goals"]},
            "pred": prediction,
        },
    }


def score_execution_prediction_task(task: TaskSpec, predicted_state: Dict[str, Any]) -> Dict[str, Any]:
    """predicted_state is a {files: {...}, dirs: [...]} snapshot claim."""
    truth_rep = validate_plan(
        task.initial_state, task.start_and_actions.get("actions", []), task.goal, task.costs
    )
    truth_final = truth_rep["snapshots"][-1]
    # compare predicted predicates (task.goal used as probe set here is not right;
    # use explicit expected_predicates field if present)
    probes = task.gold.get("expected_predicates", task.goal)
    hits = sum(1 for p in probes if predicate_holds(predicted_state, p) == predicate_holds(truth_final, p))
    primary = (hits / len(probes)) if probes else 0.0
    return {"score": round(primary, 4), "diagnostics": {"truth_final": truth_final}}


def score_task(task: TaskSpec, agent_output: Dict[str, Any]) -> Dict[str, Any]:
    """Dispatch by task type. agent_output shape is type-dependent.

    generation/optimal/replan/reuse: {plan: [...]}
    verification: {executable: bool, goal_reached: bool, first_failure_index: int|None}
    execution: {predicted_state: {files: {...}, dirs: [...]}}
    """
    if task.type in ("generation", "optimal", "replan", "reuse"):
        return score_execution_task(task, agent_output.get("plan", []))
    if task.type == "verification":
        return score_verification_task(task, agent_output)
    if task.type == "execution":
        return score_execution_prediction_task(task, agent_output.get("predicted_state", {}))
    raise ValueError(f"unknown task type {task.type!r}")
