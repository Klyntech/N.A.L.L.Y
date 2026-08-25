"""Tests for AgentSessionManager.commit_turn — voice fast-path persistence."""

import pytest

from nally.agent.sessions import AgentSessionManager


class FakeAgent:
    """Minimal stand-in for NallyAgent (no LLM/memory dependencies)."""

    def __init__(self):
        self.messages = [{"role": "system", "content": "sys"}]
        self.saved = 0

    def _save_history(self):
        self.saved += 1


@pytest.fixture
def manager(monkeypatch):
    # Never touch the real DB during session creation
    monkeypatch.setattr("nally.agent.sessions.ensure_migrated", lambda: None)
    return AgentSessionManager()


def test_commit_turn_appends_and_saves(manager, monkeypatch):
    fake = FakeAgent()
    sid = "user:111"
    manager._sessions[sid] = fake

    manager.commit_turn(sid, "what's up", "not much")
    manager.commit_turn(sid, "run tests", "done")

    roles = [m["role"] for m in fake.messages]
    assert roles == ["system", "user", "assistant", "user", "assistant"]
    assert fake.messages[1]["content"] == "what's up"
    assert fake.messages[-1]["content"] == "done"
    assert fake.saved == 2


def test_commit_turn_survives_save_failure(manager, monkeypatch):
    fake = FakeAgent()

    def boom():
        raise RuntimeError("disk full")

    fake._save_history = boom
    sid = "user:111"
    manager._sessions[sid] = fake

    # Must not raise — persistence is best-effort for voice turns
    manager.commit_turn(sid, "hello", "hi")
    assert len(fake.messages) == 3


def test_commit_turn_empty_reply_still_persists_user_side(manager):
    fake = FakeAgent()
    sid = "user:111"
    manager._sessions[sid] = fake

    manager.commit_turn(sid, "interrupted question", "")
    assert [m["role"] for m in fake.messages] == ["system", "user"]
    assert fake.saved == 1
