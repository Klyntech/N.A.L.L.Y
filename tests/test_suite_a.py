"""Suite A offline tests — no network."""
import sys
from pathlib import Path
import pytest
_project_root=str(Path(__file__).parent.parent.parent)
if _project_root not in sys.path: sys.path.insert(0,_project_root)
from tests.eval.suite_a.schema import load_all_tasks, load_task
from tests.eval.suite_t.runner import gold_trajectory, noop_trajectory, replay, run_suite

TASKS_DIR=Path(__file__).parent/"eval"/"suite_a"/"tasks"

def _degraded(task):
    ev=gold_trajectory(task)
    idx=[i for i,e in enumerate(ev) if e.get("role")=="agent"]
    if len(idx)>1: ev.pop(idx[-2])
    return ev

def test_all_validate():
    tasks=load_all_tasks(TASKS_DIR)
    assert len(tasks)==18
    errs=[]
    for t in tasks: errs.extend(t.validate())
    assert errs==[], errs

def test_gold_one():
    for t in load_all_tasks(TASKS_DIR):
        assert replay(t, gold_trajectory(t))["score"]==1.0, t.id

def test_noop_refusal():
    for t in load_all_tasks(TASKS_DIR):
        r=replay(t, noop_trajectory(t))
        exp=1.0 if t.category=="II" else 0.0
        assert r["score"]==exp, t.id

def test_degraded_gap():
    gold=run_suite(TASKS_DIR, builder=gold_trajectory)
    deg=run_suite(TASKS_DIR, builder=_degraded)
    assert gold["mean_score"]-deg["mean_score"]>=0.10
