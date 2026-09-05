"""plan_critiqued was a black-hole EventBus publish; must not return."""

from pathlib import Path


def test_planner_does_not_publish_plan_critiqued():
    src = Path("nally/agent/planner.py").read_text()
    assert "plan_critiqued" not in src


def test_live_plan_events_still_published():
    src = Path("nally/agent/planner.py").read_text()
    for name in ("plan_created", "plan_step_started", "plan_step_completed", "plan_complete"):
        assert f'"{name}"' in src or f"'{name}'" in src, name
