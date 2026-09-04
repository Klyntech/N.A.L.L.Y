"""Architectural tests for automatic TaskRouter strategy selection."""

from nally.agent.harness import Classification, TaskClass
from nally.agent.task_router import Strategy, route, route_from_classification


def test_simple_goes_react():
    c = Classification(TaskClass.SIMPLE, 0.95, "greeting")
    d = route_from_classification(c, "hello")
    assert d.strategy == Strategy.REACT
    assert not d.needs_plan


def test_complex_goes_plan():
    c = Classification(TaskClass.COMPLEX, 0.9, "multi-step")
    d = route_from_classification(c, "build auth with tests and deploy")
    assert d.strategy == Strategy.PLAN
    assert d.needs_plan


def test_high_stakes_goes_plan():
    c = Classification(TaskClass.HIGH_STAKES, 0.88, "risky")
    d = route_from_classification(c, "delete production database backup")
    assert d.strategy == Strategy.PLAN


def test_plan_signals_without_harness():
    d = route(
        "First set up the database, then create the API, and finally write end to end tests"
    )
    assert d.strategy == Strategy.PLAN


def test_engineering_signals():
    d = route("refactor the entire codebase architecture and rewrite the module system")
    assert d.strategy == Strategy.ENGINEERING
    assert d.needs_plan


def test_plan_kill_switch(monkeypatch):
    import nally.agent.task_router as tr

    monkeypatch.setattr(tr, "PLAN_ENABLED", False, raising=False)
    # patch via config import path used inside route()
    import nally.config as cfg

    monkeypatch.setattr(cfg, "PLAN_ENABLED", False)
    c = Classification(TaskClass.COMPLEX, 0.9, "multi-step")
    d = route("build a full system with tests", classification=c)
    assert d.strategy == Strategy.REACT
    assert not d.needs_plan
