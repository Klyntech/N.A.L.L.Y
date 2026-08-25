"""Tests for nally.agent.identity — cross-platform session resolution."""

import pytest

from nally.agent import identity
from nally.agent.identity import SessionRef, resolve_session


@pytest.fixture(autouse=True)
def _reset_identity_state():
    """Isolate owner detection / migration flags between tests."""
    identity._detected_owner = None
    identity._migrated = True  # never touch the real DB from these tests
    yield
    identity._detected_owner = None
    identity._migrated = True


@pytest.fixture
def owner_111(monkeypatch):
    monkeypatch.setattr(identity, "get_owner_id", lambda: 111)
    return 111


# ── Resolver mapping ──────────────────────────────────────


def test_web_maps_to_owner_session(owner_111):
    ref = resolve_session("web")
    assert ref.session_id == "user:111"
    assert ref.route_key == "web:default"
    assert ref.channel == "Web"
    # Invariant: route_key != session_id for multi-channel owners.
    assert ref.route_key != ref.session_id


def test_telegram_dm_owner_shares_brain(owner_111):
    ref = resolve_session("telegram", chat_id=111)
    assert ref.session_id == "user:111"
    assert ref.route_key == "telegram:111"


def test_telegram_group_stays_separate(owner_111):
    ref = resolve_session("telegram", chat_id=-100123, is_group=True)
    assert ref.session_id == "telegram:group:-100123"
    assert ref.route_key == ref.session_id  # groups: unchanged legacy ids


def test_non_owner_gets_own_session(owner_111):
    ref = resolve_session("telegram", chat_id=999)
    assert ref.session_id == "user:999"
    assert ref.session_id != resolve_session("web").session_id


def test_tg_user_maps_like_bot_dm(owner_111):
    assert resolve_session("tg_user", sender_id=111).session_id == "user:111"
    assert resolve_session("tg_user", sender_id=999).session_id == "user:999"


def test_voice_call_maps_to_owner_brain(owner_111):
    ref = resolve_session("tg_voice", chat_id=111)
    assert ref.session_id == "user:111"
    assert ref.route_key == "tg_voice:111"


def test_voip_owner_and_non_owner(owner_111):
    assert resolve_session("voip", sender_id="111").session_id == "user:111"
    assert resolve_session("voip", sender_id="999").session_id == "user:999"


def test_local_voice_loop_maps_to_owner(owner_111):
    ref = resolve_session("voice")
    assert ref.session_id == "user:111"
    assert ref.channel == "Voice"


def test_unknown_channel_defaults_to_owner(owner_111):
    ref = resolve_session("carrier_pigeon")
    assert ref.session_id == "user:111"


# ── Owner detection / fallback ────────────────────────────


def test_no_owner_falls_back_to_literal():
    monkey_owner = lambda: None
    orig = identity.get_owner_id
    identity.get_owner_id = monkey_owner
    try:
        assert identity.owner_session_id() == "user:owner"
        ref = resolve_session("web")
        assert ref.session_id == "user:owner"
    finally:
        identity.get_owner_id = orig


def test_note_owner_detects_first_sender(monkeypatch):
    monkeypatch.setattr(identity, "configured_owner_id", lambda: None)
    assert identity.note_owner(555) == 555
    assert identity.owner_session_id() == "user:555"
    # First detection wins
    assert identity.note_owner(777) == 555


def test_note_owner_respects_configured(monkeypatch):
    monkeypatch.setattr(identity, "configured_owner_id", lambda: 42)
    assert identity.note_owner(555) is None
    assert identity.owner_session_id() == "user:42"


def test_single_user_mode_treats_anyone_as_owner(monkeypatch):
    monkeypatch.setattr(identity, "configured_owner_id", lambda: None)
    identity._detected_owner = None
    assert resolve_session("telegram", chat_id=321).session_id == "user:owner"# ── History migration ─────────────────────────────────────


def test_merge_sessions_into_copies_and_caps(tmp_path):
    from nally.memory.store import MemoryRepository

    store = MemoryRepository(db_path=tmp_path / "mem.db")
    store.save_messages(
        [{"role": "user", "content": "w1"}, {"role": "assistant", "content": "w2"}],
        session_id="web:default",
    )
    store.save_messages([{"role": "user", "content": "t1"}], session_id="telegram:111")
    store.save_messages([{"role": "user", "content": "u1"}], session_id="tg_user:111")

    copied = store.merge_sessions_into(
        ["web:default", "telegram:111", "tg_user:111"], "user:111", limit=200
    )
    assert copied == 4
    merged = store.load_messages("user:111")
    assert [m["content"] for m in merged] == ["w1", "w2", "t1", "u1"]


def test_merge_sessions_into_skips_when_target_has_history(tmp_path):
    from nally.memory.store import MemoryRepository

    store = MemoryRepository(db_path=tmp_path / "mem.db")
    store.save_messages([{"role": "user", "content": "old"}], session_id="web:default")
    store.save_messages([{"role": "assistant", "content": "existing"}], session_id="user:111")

    assert store.merge_sessions_into(["web:default"], "user:111", limit=200) == 0
    assert len(store.load_messages("user:111")) == 1


def test_migrate_owner_history_respects_env_limit(tmp_path, monkeypatch):
    import nally.memory as mem_pkg
    from nally.memory.store import MemoryRepository

    store = MemoryRepository(db_path=tmp_path / "mem.db")
    store.save_messages(
        [{"role": "user", "content": f"m{i}"} for i in range(10)],
        session_id="web:default",
    )
    store.save_messages(
        [{"role": "assistant", "content": f"t{i}"} for i in range(10)],
        session_id="telegram:111",
    )

    monkeypatch.setenv("NALLY_HISTORY_MIGRATE_LIMIT", "6")
    monkeypatch.setattr(identity, "get_owner_id", lambda: 111)
    # migrate_owner_history imports the singleton lazily from ..memory
    monkeypatch.setattr(mem_pkg, "memory_store", store, raising=False)

    copied = identity.migrate_owner_history()
    assert copied == 6
    merged = store.load_messages("user:111")
    assert len(merged) == 6
    # Cap keeps the LAST messages (time-ordered merge across sources)
    assert [m["content"] for m in merged] == ["t4", "t5", "t6", "t7", "t8", "t9"]


def test_migrate_owner_history_skips_without_sources(tmp_path, monkeypatch):
    import nally.memory as mem_pkg
    from nally.memory.store import MemoryRepository

    store = MemoryRepository(db_path=tmp_path / "mem.db")
    store.save_messages([{"role": "user", "content": "x"}], session_id="group:1")

    monkeypatch.setattr(identity, "get_owner_id", lambda: 111)
    monkeypatch.setattr(mem_pkg, "memory_store", store, raising=False)

    # Only web:default/telegram:111/tg_user:111/tg_voice:111 are sources;
    # group history stays untouched.
    assert identity.migrate_owner_history() == 0
