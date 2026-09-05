"""TaskState keys must match agent brain session_id, not config SESSION_ID drift."""

from __future__ import annotations

from pathlib import Path

from nally.tools.task_state import TaskState, task_state_manager


def test_save_and_resume_same_brain():
    sid = "user:alice-taskstate"
    task_state_manager.delete(sid)
    st = TaskState(sid)
    st.task_description = "Build the thing"
    st.status = "in_progress"
    st.pending_steps = ["step1"]
    task_state_manager.save(st)

    loaded = task_state_manager.get(sid)
    assert loaded is not None
    assert loaded.session_id == sid
    assert loaded.task_description == "Build the thing"
    task_state_manager.delete(sid)


def test_resume_other_brain_does_not_see_task():
    alice = "user:alice-iso"
    bob = "user:bob-iso"
    task_state_manager.delete(alice)
    task_state_manager.delete(bob)

    st = TaskState(alice)
    st.task_description = "Alice only"
    st.status = "in_progress"
    task_state_manager.save(st)

    assert task_state_manager.get(alice) is not None
    assert task_state_manager.get(bob) is None
    task_state_manager.delete(alice)


def test_default_row_is_not_alice_resume():
    alice = "user:alice-not-default"
    default = "default"
    task_state_manager.delete(alice)
    task_state_manager.delete(default)

    st = TaskState(default)
    st.task_description = "Orphan default row"
    st.status = "in_progress"
    task_state_manager.save(st)

    assert task_state_manager.get(alice) is None
    assert task_state_manager.get(default) is not None
    task_state_manager.delete(default)


def test_same_brain_web_and_telegram_share_task_state():
    """Cross-channel: same session_id is one TaskState row."""
    brain = "user:owner-cross-channel"
    task_state_manager.delete(brain)
    st = TaskState(brain)
    st.task_description = "Shared brain work"
    st.status = "in_progress"
    st.files_created = ["a.py"]
    task_state_manager.save(st)

    # Web and Telegram resolve to same brain session_id
    web_resume = task_state_manager.get(brain)
    tg_resume = task_state_manager.get(brain)
    assert web_resume is not None and tg_resume is not None
    assert web_resume.files_created == ["a.py"]
    assert tg_resume.task_description == "Shared brain work"
    task_state_manager.delete(brain)


def test_graph_autosave_uses_session_id_from_agent_state():
    """Production path: graph auto-save reads state['session_id'], not only SESSION_ID."""
    src = Path("nally/agent/graph.py").read_text()
    assert 'brain_id = state.get("session_id") or SESSION_ID' in src
    assert "TaskState(SESSION_ID)" not in src or 'TaskState(brain_id)' in src
    # Auto-save must not exclusively key on SESSION_ID anymore
    assert "task_state_manager.get(SESSION_ID)" not in src
    assert "task_state_manager.get(brain_id)" in src
    assert "task_state_manager.save(task_st)" in src
    # AgentState carries stable brain id into the graph
    assert "session_id: str" in src
    assert '"session_id": thread_id' in src


def test_core_resume_uses_agent_session_id():
    src = Path("nally/agent/core.py").read_text()
    assert "task_state_manager.get(self._session_id)" in src
