"""Human checkpoint: timeout fails closed — silence is not authorization."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

from nally.agent import human_checkpoint as hcp
from nally.agent.human_checkpoint import (
    get_checkpoint,
    human_checkpoint_node,
    resolve_checkpoint,
)


@pytest.fixture
def cp_db(tmp_path, monkeypatch):
    """Isolate human_checkpoints SQLite under tmp_path."""
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(hcp, "DATA_DIR", data)
    # Also patch module-level import of DATA_DIR used in _get_checkpoint_db
    monkeypatch.setattr("nally.agent.human_checkpoint.DATA_DIR", data)
    monkeypatch.setattr(hcp, "HUMAN_CHECKPOINT_POLL_INTERVAL_SEC", 0)
    return data


def _base_state(**kwargs):
    st = {
        "intent_class": "COMPLEX",
        "thread_id": "user:owner-test-abc12345",
        "plan": {
            "goal": "Do a thing",
            "status": "active",
            "steps": [{"id": "s1", "goal": "step one", "status": "pending"}],
            "summary": "",
            "critique": None,
            "revision_count": 0,
            "created_at": 0,
        },
        "messages": [],
        "plan_status": "planning",
    }
    st.update(kwargs)
    return st


def test_timeout_rejects_not_approves(cp_db, monkeypatch):
    monkeypatch.setattr(hcp, "HUMAN_CHECKPOINT_MAX_POLLS", 0)
    tid = "timeout-reject-thread"
    state = _base_state(thread_id=tid)
    with patch("nally.events.bus.event_bus"):
        out = human_checkpoint_node(state)
    assert out.get("plan_status") == "rejected"
    cp = get_checkpoint(tid)
    assert cp is not None
    assert cp.status == "rejected"
    assert out.get("plan_status") != "executing"


def test_timeout_never_executing_for_high_stakes(cp_db, monkeypatch):
    monkeypatch.setattr(hcp, "HUMAN_CHECKPOINT_MAX_POLLS", 0)
    tid = "timeout-high-stakes"
    state = _base_state(thread_id=tid, intent_class="HIGH_STAKES")
    with patch("nally.events.bus.event_bus"):
        out = human_checkpoint_node(state)
    assert out["plan_status"] == "rejected"
    assert get_checkpoint(tid).status == "rejected"


def test_timeout_rejects_creative_and_complex(cp_db, monkeypatch):
    monkeypatch.setattr(hcp, "HUMAN_CHECKPOINT_MAX_POLLS", 0)
    for intent in ("COMPLEX", "CREATIVE", "HIGH_STAKES"):
        tid = f"timeout-{intent.lower()}"
        with patch("nally.events.bus.event_bus"):
            out = human_checkpoint_node(_base_state(thread_id=tid, intent_class=intent))
        assert out["plan_status"] == "rejected", intent
        assert get_checkpoint(tid).status == "rejected"


def test_abort_rejects(cp_db, monkeypatch):
    monkeypatch.setattr(hcp, "HUMAN_CHECKPOINT_MAX_POLLS", 50)
    tid = "abort-reject-thread"
    state = _base_state(thread_id=tid)

    def check_side_effect(key):
        check_side_effect.n += 1
        return check_side_effect.n > 1

    check_side_effect.n = 0
    with patch("nally.events.bus.event_bus"), patch(
        "nally.core.abort.check_abort", side_effect=check_side_effect
    ):
        out = human_checkpoint_node(state)
    assert out["plan_status"] == "rejected"
    assert get_checkpoint(tid).status == "rejected"


def test_normal_approval_still_executes(cp_db, monkeypatch):
    monkeypatch.setattr(hcp, "HUMAN_CHECKPOINT_MAX_POLLS", 20)
    tid = "approve-ok-thread"
    state = _base_state(thread_id=tid)
    real_get = hcp.get_checkpoint
    polls = {"n": 0}

    def get_then_approve(thread_id):
        polls["n"] += 1
        if polls["n"] >= 1:
            resolve_checkpoint(thread_id, "approved")
        return real_get(thread_id)

    with patch("nally.events.bus.event_bus"), patch(
        "nally.core.abort.check_abort", return_value=False
    ), patch.object(hcp, "get_checkpoint", side_effect=get_then_approve):
        out = human_checkpoint_node(state)
    assert out["plan_status"] == "executing"
    assert get_checkpoint(tid).status == "approved"


def test_normal_edit_still_executes_edited_plan(cp_db, monkeypatch):
    monkeypatch.setattr(hcp, "HUMAN_CHECKPOINT_MAX_POLLS", 20)
    tid = "edit-ok-thread"
    state = _base_state(thread_id=tid)
    real_get = hcp.get_checkpoint
    polls = {"n": 0}

    def get_then_edit(thread_id):
        polls["n"] += 1
        if polls["n"] >= 1:
            resolve_checkpoint(thread_id, "edited", edited_plan="revised step one")
        return real_get(thread_id)

    with patch("nally.events.bus.event_bus"), patch(
        "nally.core.abort.check_abort", return_value=False
    ), patch.object(hcp, "get_checkpoint", side_effect=get_then_edit):
        out = human_checkpoint_node(state)
    assert out["plan_status"] == "executing"
    plan = out.get("plan")
    assert plan is not None
    steps = plan.get("steps") if isinstance(plan, dict) else None
    if steps:
        assert "revised" in str(steps[0].get("goal", "")).lower()


def test_simple_intent_skips_checkpoint(cp_db):
    out = human_checkpoint_node(_base_state(intent_class="SIMPLE"))
    assert out.get("plan_status") != "rejected"


def test_timeout_message_present(cp_db, monkeypatch):
    monkeypatch.setattr(hcp, "HUMAN_CHECKPOINT_MAX_POLLS", 0)
    tid = "timeout-msg"
    with patch("nally.events.bus.event_bus"):
        out = human_checkpoint_node(_base_state(thread_id=tid))
    msgs = out.get("messages") or []
    assert msgs
    content = getattr(msgs[0], "content", "") or ""
    assert "timed out" in content.lower()
