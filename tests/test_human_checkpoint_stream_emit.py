"""Human checkpoint must reach the live stream emit path clients already consume."""

from __future__ import annotations

from pathlib import Path

from unittest.mock import patch

import pytest

from nally.agent import human_checkpoint as hcp
from nally.agent.emit_context import get_emit, set_emit
from nally.agent.human_checkpoint import get_checkpoint, human_checkpoint_node, resolve_checkpoint


@pytest.fixture
def cp_db(tmp_path, monkeypatch):
    data = tmp_path / "data"
    data.mkdir()
    monkeypatch.setattr(hcp, "DATA_DIR", data)
    monkeypatch.setattr("nally.agent.human_checkpoint.DATA_DIR", data)
    monkeypatch.setattr(hcp, "HUMAN_CHECKPOINT_POLL_INTERVAL_SEC", 0)
    monkeypatch.setattr(hcp, "HUMAN_CHECKPOINT_MAX_POLLS", 0)
    yield data
    set_emit(None)


def _base_state(**kwargs):
    st = {
        "intent_class": "COMPLEX",
        "thread_id": "user:owner-stream-abcdef12",
        "plan": {
            "goal": "Ship feature",
            "status": "active",
            "steps": [{"id": "s1", "goal": "write tests", "status": "pending"}],
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


def test_stream_receives_exactly_one_human_checkpoint_required(cp_db):
    events = []

    def stream_emit(event, payload):
        events.append((event, dict(payload)))

    set_emit(stream_emit)
    try:
        with patch("nally.events.bus.event_bus"):
            human_checkpoint_node(_base_state(thread_id="stream-one-cp"))
    finally:
        set_emit(None)

    cp_events = [e for e in events if e[0] == "human_checkpoint_required"]
    assert len(cp_events) == 1
    payload = cp_events[0][1]
    assert payload["thread_id"] == "stream-one-cp"
    assert payload.get("plan_summary")
    assert isinstance(payload.get("steps"), list)
    assert payload.get("task_class") == "COMPLEX"
    assert payload.get("status") == "pending"


def test_payload_thread_id_matches_saved_row(cp_db):
    events = []
    set_emit(lambda e, p: events.append((e, p)))
    tid = "stream-match-row"
    try:
        with patch("nally.events.bus.event_bus"):
            human_checkpoint_node(_base_state(thread_id=tid))
    finally:
        set_emit(None)
    assert events[0][1]["thread_id"] == tid
    row = get_checkpoint(tid)
    assert row is not None
    assert row.thread_id == tid


def test_complex_high_stakes_creative_all_emit(cp_db):
    for intent in ("COMPLEX", "HIGH_STAKES", "CREATIVE"):
        events = []
        set_emit(lambda e, p, bag=events: bag.append((e, p)))
        tid = f"stream-{intent.lower()}"
        try:
            with patch("nally.events.bus.event_bus"):
                human_checkpoint_node(_base_state(thread_id=tid, intent_class=intent))
        finally:
            set_emit(None)
        assert any(e[0] == "human_checkpoint_required" for e in events), intent
        assert events[0][1]["task_class"] == intent


def test_simple_skips_emit_and_checkpoint(cp_db):
    events = []
    set_emit(lambda e, p: events.append((e, p)))
    try:
        with patch("nally.events.bus.event_bus"):
            out = human_checkpoint_node(_base_state(intent_class="SIMPLE"))
    finally:
        set_emit(None)
    assert not any(e[0] == "human_checkpoint_required" for e in events)
    assert out.get("plan_status") != "rejected"


def test_approval_with_delivered_thread_id_still_works(cp_db, monkeypatch):
    monkeypatch.setattr(hcp, "HUMAN_CHECKPOINT_MAX_POLLS", 20)
    events = []
    tid = "stream-approve-path"
    real_get = hcp.get_checkpoint
    polls = {"n": 0}

    def get_after_client_resolve(thread_id):
        polls["n"] += 1
        if polls["n"] >= 1 and events:
            delivered = events[0][1]["thread_id"]
            assert delivered == thread_id
            resolve_checkpoint(delivered, "approved")
        return real_get(thread_id)

    set_emit(lambda e, p: events.append((e, p)))
    try:
        with patch("nally.events.bus.event_bus"), patch(
            "nally.core.abort.check_abort", return_value=False
        ), patch.object(hcp, "get_checkpoint", side_effect=get_after_client_resolve):
            out = human_checkpoint_node(_base_state(thread_id=tid))
    finally:
        set_emit(None)
    assert out["plan_status"] == "executing"
    assert events and events[0][1]["thread_id"] == tid


def test_timeout_still_fail_closed_after_emit(cp_db, monkeypatch):
    monkeypatch.setattr(hcp, "HUMAN_CHECKPOINT_MAX_POLLS", 0)
    events = []
    set_emit(lambda e, p: events.append((e, p)))
    tid = "stream-timeout-fc"
    try:
        with patch("nally.events.bus.event_bus"):
            out = human_checkpoint_node(_base_state(thread_id=tid))
    finally:
        set_emit(None)
    assert events
    assert out["plan_status"] == "rejected"
    assert get_checkpoint(tid).status == "rejected"


def test_get_emit_is_same_callback_ws_sse_pattern(cp_db):
    """Same thread-local installed by run_agent → WS/SSE stream_event."""
    seen = []

    def client_queue_put(event, payload):
        seen.append({"type": event, **payload})

    set_emit(client_queue_put)
    assert get_emit() is client_queue_put
    try:
        with patch("nally.events.bus.event_bus"):
            human_checkpoint_node(_base_state(thread_id="stream-queue-shape"))
    finally:
        set_emit(None)
    assert seen
    assert seen[0]["type"] == "human_checkpoint_required"
    assert "thread_id" in seen[0]


def test_no_emit_when_callback_unset_still_saves(cp_db, monkeypatch):
    monkeypatch.setattr(hcp, "HUMAN_CHECKPOINT_MAX_POLLS", 0)
    set_emit(None)
    tid = "stream-no-emit"
    with patch("nally.events.bus.event_bus"):
        out = human_checkpoint_node(_base_state(thread_id=tid))
    assert get_checkpoint(tid) is not None
    assert out["plan_status"] == "rejected"


def test_human_checkpoint_does_not_publish_to_event_bus():
    """Client path is emit; bus publish was residue with no consumer."""
    src = Path("nally/agent/human_checkpoint.py").read_text()
    assert "event_bus.publish" not in src
    assert "from ..events.bus import event_bus" not in src
