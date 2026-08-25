"""Cross-platform session identity — one brain per person.

Canonical mapping:

    person  -> session_id = "user:{owner}"   (shared agent brain + history)
    channel -> route_key  = "telegram:{chat}" | "web:default" | "tg_voice:{id}"
    group   -> session_id = "telegram:group:{id}"  (kept separate, unchanged)

Invariant: route_key NEVER equals session_id for a multi-channel owner.
route_key scopes streaming events (SQLite stream_events), WebSocket rooms and
media folders so channels don't bleed into each other's UIs. session_id scopes
the brain: one conversation thread + persisted history per person.

Owner resolution order:
    1. TELEGRAM_USER_ID env var (config)
    2. First Telegram DM sender (single-user auto-detection)
    3. Fallback literal "owner" -> "user:owner"

Non-owner senders get their own "user:{id}" session (hosted/Pro ready).
"""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass
from typing import List, Optional

from ..utils.logger import logger


@dataclass(frozen=True)
class SessionRef:
    """Where a message routes: the shared brain + the channel plumbing key."""

    session_id: str
    route_key: str
    channel: str


_lock = threading.Lock()
_detected_owner: Optional[int] = None
_migrated = False


def configured_owner_id() -> Optional[int]:
    """Owner id from config/env, or None if unset."""
    from ..config import TELEGRAM_USER_ID

    try:
        return int(TELEGRAM_USER_ID) if TELEGRAM_USER_ID else None
    except (TypeError, ValueError):
        return None


def note_owner(sender_id) -> Optional[int]:
    """Record the first-seen Telegram sender as owner (single-user mode).

    No-op when TELEGRAM_USER_ID is already configured.
    """
    global _detected_owner
    if not sender_id:
        return _detected_owner
    with _lock:
        if _detected_owner is None and configured_owner_id() is None:
            _detected_owner = int(sender_id)
            logger.info(f"Session owner detected: {_detected_owner}")
    return _detected_owner


def get_owner_id() -> Optional[int]:
    return configured_owner_id() or _detected_owner


def owner_session_id() -> str:
    """Canonical shared-brain session id for the owner."""
    owner = get_owner_id()
    return f"user:{owner}" if owner else "user:owner"


def _is_owner(user_id) -> bool:
    if user_id is None:
        return False
    owner = get_owner_id()
    # No owner known yet -> single-user mode: treat everyone as the owner.
    return True if owner is None else int(user_id) == int(owner)


def resolve_session(
    channel: str,
    chat_id=None,
    sender_id=None,
    is_group: bool = False,
) -> SessionRef:
    """Map an inbound message to (brain session, routing key, channel label).

    DMs, web chat, voice notes, voice calls and VoIP all land on the owner's
    single session so the brain and recent history are shared across platforms.
    Groups keep their existing per-group session ids (preserves group history).
    """
    if channel == "web":
        return SessionRef(owner_session_id(), "web:default", "Web")

    if channel == "voice":
        sid = owner_session_id()
        return SessionRef(sid, f"voice:{sid}", "Voice")

    if channel == "voip":
        who = sender_id or chat_id
        sid = owner_session_id() if (who is None or _is_owner(who)) else f"user:{who}"
        return SessionRef(sid, f"voip:{who or 'unknown'}", "VoIP call")

    if channel in ("telegram", "tg_user"):
        label = "Telegram" if channel == "telegram" else "Telegram user account"
        if is_group:
            route = f"telegram:group:{chat_id}"
            # Group session id unchanged from the old scheme — keeps history.
            return SessionRef(route, route, f"{label} group")
        who = sender_id or chat_id
        if who is not None and not _is_owner(who):
            return SessionRef(f"user:{who}", f"{channel}:{who}", label)
        return SessionRef(owner_session_id(), f"{channel}:{chat_id}", label)

    if channel == "tg_voice":
        who = sender_id or chat_id
        label = "Telegram voice call"
        if who is not None and not _is_owner(who):
            return SessionRef(f"user:{who}", f"tg_voice:{chat_id}", label)
        return SessionRef(owner_session_id(), f"tg_voice:{chat_id}", label)

    # Unknown channel — safest default is the owner brain.
    return SessionRef(owner_session_id(), f"{channel}:default", channel.replace("_", " ").title())


# ── One-time owner history migration ────────────────────────


def migrate_owner_history(limit: Optional[int] = None) -> int:
    """Merge old per-channel owner histories into the unified owner session.

    Sources: web:default + telegram/tg_user/tg_voice rows for the owner id
    (when known). Time-sorted merge capped at `limit` messages (default from
    NALLY_HISTORY_MIGRATE_LIMIT env, else 200). Old rows stay in place; the
    merge is skipped entirely once the target session has any history.

    Returns the number of messages copied (0 when skipped).
    """
    if limit is None:
        limit = int(os.getenv("NALLY_HISTORY_MIGRATE_LIMIT", "200"))

    target = owner_session_id()

    sources: List[str] = ["web:default"]
    owner = get_owner_id()
    if owner:
        sources += [f"telegram:{owner}", f"tg_user:{owner}", f"tg_voice:{owner}"]

    from ..memory import memory_store

    copied = memory_store.merge_sessions_into(sources, target, limit=limit)
    if copied:
        logger.info(f"Migrated {copied} messages into unified session {target}")
    return copied


def ensure_migrated() -> None:
    """Run migrate_owner_history once per process (best-effort)."""
    global _migrated
    with _lock:
        if _migrated:
            return
        _migrated = True
    try:
        migrate_owner_history()
    except Exception as e:
        logger.warning(f"Owner history migration skipped: {type(e).__name__}: {e}")
