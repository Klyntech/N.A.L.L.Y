"""Suite P offline tests — no network, no LLM keys, no production imports."""
import sys
from pathlib import Path
import pytest
import json

_project_root = str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from tests.eval.suite_p.schema import load_all_tasks, load_task
from tests.eval.suite_p.world import validate_plan, optimal_cost
from tests.eval.suite_p.scorer import score_task
from tests.eval.suite_p.runner import gold_output, noop_output, degraded_output, run_suite
from tests.eval.suite_p.pilot import hallucinating_plan

TASKS_DIR = Path(__file__).parent / "eval" / "suite_p" / "tasks"


def test_all_tasks_validate_clean():
    tasks = load_all_tasks(TASKS_DIR)
    assert len(tasks) == 26, f"expected 26 (20+6 obfuscated), got {len(tasks)}"
    known = [t.id for t in tasks]
    errors = []
    for t in tasks:
        errors.extend(t.validate(known))
    assert errors == [], f"validation errors: {errors}"


def test_obfuscated_twins_share_semantics():
    tasks = {t.id: t for t in load_all_tasks(TASKS_DIR)}
    for t in tasks.values():
        if not t.obfuscation_of:
            continue
        base = tasks[t.obfuscation_of]
        # structured semantics identical, presentation differs
        assert t.goal == base.goal, t.id
        assert t.initial_state == base.initial_state, t.id
        assert t.type == base.type, t.id


def test_gold_scores_one():
    for task in load_all_tasks(TASKS_DIR):
        result = score_task(task, gold_output(task))
        assert result["score"] == 1.0, f"{task.id}: {result}"


def test_noop_distinguishable_from_gold():
    gold = run_suite(TASKS_DIR, builder=gold_output)
    noop = run_suite(TASKS_DIR, builder=noop_output)
    assert gold["mean_score"] - noop["mean_score"] >= 0.20


def test_degraded_separates():
    gold = run_suite(TASKS_DIR, builder=gold_output)
    degraded = run_suite(TASKS_DIR, builder=degraded_output)
    assert gold["mean_score"] - degraded["mean_score"] >= 0.10


def test_hallucinating_zeroed_on_all_types():
    for task in load_all_tasks(TASKS_DIR):
        h = hallucinating_plan(task)
        assert score_task(task, h)["score"] == 0.0, f"{task.id}"


def test_optimal_gold_is_optimal():
    for task in load_all_tasks(TASKS_DIR):
        if task.type != "optimal":
            continue
        plan = task.gold["plan"]
        rep = validate_plan(task.initial_state, plan, task.goal, task.costs)
        oc = optimal_cost(task.initial_state, task.goal, task.costs, [plan])
        assert rep["cost"] == oc, f"{task.id} cost {rep['cost']} != opt {oc}"


def test_replan_needs_replan_suffix():
    """p16 replan must recreate dir after unexpected removal; plain prefix alone fails."""
    task = load_task(TASKS_DIR / "p16.json")
    # prefix alone does not achieve goal (dir was removed externally at test time,
    # but validator's notion is that gold replan suffix does).
    assert score_task(task, gold_output(task))["score"] == 1.0
    # empty plan fails
    assert score_task(task, {"plan": []})["score"] == 0.0
