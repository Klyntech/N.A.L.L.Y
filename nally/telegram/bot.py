"""Nally Telegram Bot — DM + group chat via python-telegram-bot.

Supports:
- Text messages: process through agent, reply as text
- Voice messages: STT -> agent -> voice reply (LLM summary spoken, full text on screen)

Requires TELEGRAM_BOT_TOKEN in .env.
ffmpeg required for voice support.
"""

import asyncio
import io
import os
import re
import threading
import time
from typing import Optional

from telegram.constants import UpdateType
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)
from telegram.request import HTTPXRequest

from telegram import Update

from ..agent.sessions import session_manager
from ..utils.logger import logger
from .format import md_to_telegram_html

# ── DNS 11001 spam filter: collapse httpx getaddrinfo failures to one warning ──
import logging as _logging

class _GetAddrInfoFilter(_logging.Filter):
    """Collapse Telegram polling DNS failures (11001 getaddrinfo) to a single warning.

    python-telegram-bot logs the full 20-line httpx/httpcore chain at ERROR
    with exc_info on every poll. We rewrite it to a one-liner and downgrade to
    WARNING so the console isn't flooded while DNS is down.
    """
    _last_log = 0.0  # rate-limit to 1 per 30s

    def filter(self, record: _logging.LogRecord) -> bool:
        msg = record.getMessage() + " " + str(getattr(record, "exc_info", "") or "")
        if "getaddrinfo failed" in msg or "11001" in msg or "WinError 1231" in msg or "WinError 1236" in msg:
            # Rate-limit: only log once per 30s, drop the rest
            import time as _time
            now = _time.monotonic()
            if now - self._last_log < 30:
                return False
            self._last_log = now
            # Rewrite to single helpful warning, no stack
            record.levelno = _logging.WARNING
            record.levelname = "WARNING"
            record.exc_info = None
            record.exc_text = None
            record.msg = "Telegram polling DNS/network down (getaddrinfo 11001 / WinError 1231) — check internet/DNS/proxy for api.telegram.org. Retrying…"
            record.args = ()
            return True
        return True

# Install on the noisy loggers (httpx/httpcore/telegram)
# Suppress Telegram library loggers to WARNING to stop stack trace spam.
# The library uses CamelCase logger names (telegram.ext.Updater, not telegram.ext._updater).
for _lname in ("telegram.ext.Updater", "telegram.request.BaseRequest", "telegram.request.HTTPXRequest", "httpx", "httpcore"):
    try:
        _logging.getLogger(_lname).addFilter(_GetAddrInfoFilter())
        _logging.getLogger(_lname).setLevel(_logging.WARNING)
    except Exception:
        pass
# Also quiet Telethon's network spam a bit (keep WARNING, not INFO for connect retries)
for _lname in ("telethon.network.mtprotosender", "telethon.network.connection.connection"):
    try:
        _logging.getLogger(_lname).setLevel(_logging.WARNING)
    except Exception:
        pass

# Telegram max message length
MAX_MSG_LEN = 4096
BOT_USERNAME: Optional[str] = None
BOT = None  # set in post_init, used by _make_emit for approval messages
_start_time = time.time()


def _web_base_url() -> str:
    """Base URL of the web server the standalone bot forwards to.

    Reads NALLY_BASE_URL first (e.g. https://nally.onrender.com).
    Falls back to http://localhost:<port> for local dev.
    """
    from ..config import NALLY_BASE_URL
    if NALLY_BASE_URL:
        return NALLY_BASE_URL
    port = os.getenv("NALLY_PORT", os.getenv("PORT", "5000"))
    return f"http://localhost:{port}"

# Telegram send retry policy (mirrors _call_llm_with_retry in agent/graph.py)
_TG_MAX_RETRIES = 3
_TG_RETRYABLE_CODES = {"429", "500", "502", "503"}


async def _send_with_retry(coro_factory, *args, **kwargs):
    """Await a Telegram send coroutine with backoff retry.

    Mirrors the _call_llm_with_retry shape: retries on transient network
    errors / HTTP 429/5xx, exponential backoff min(2^(attempt+1), 15) seconds.
    Raises the last error if all retries are exhausted. Does NOT catch the
    raised error — callers must handle it.
    """
    from telegram.error import NetworkError, RetryAfter, TimedOut

    last_error = None
    for attempt in range(_TG_MAX_RETRIES):
        try:
            return await coro_factory(*args, **kwargs)
        except Exception as e:
            last_error = e
            error_str = str(e).lower()
            is_retryable = isinstance(e, (RetryAfter, TimedOut, NetworkError)) or any(
                code in error_str for code in _TG_RETRYABLE_CODES
            )
            if attempt < _TG_MAX_RETRIES - 1 and is_retryable:
                wait = min(2 ** (attempt + 1), 15)
                logger.warning(
                    f"Telegram send failed (attempt {attempt + 1}/{_TG_MAX_RETRIES}), "
                    f"retrying in {wait}s: {str(e)[:80]}"
                )
                await asyncio.sleep(wait)
            else:
                break
    if last_error:
        raise last_error
    return None


def _split_message(text: str, limit: int = MAX_MSG_LEN) -> list:
    """Split long messages at paragraph/break boundaries."""
    if len(text) <= limit:
        return [text]

    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        # Try to split at a paragraph break
        split_at = text.rfind("\n\n", 0, limit)
        if split_at < limit // 2:
            # No good paragraph break — try newline
            split_at = text.rfind("\n", 0, limit)
        if split_at < limit // 2:
            # No good break — force split at limit
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


def _extract_session_ref(update: Update):
    """Resolve a Telegram update to (brain session, route key, channel label).

    DMs land on the owner's shared session (same brain as web/voice); groups
    keep their own per-group session.
    """
    from ..agent.identity import resolve_session

    chat = update.effective_chat
    is_group = chat.type in ("group", "supergroup")
    return resolve_session("telegram", chat_id=chat.id, is_group=is_group)


def _extract_session_id(update: Update) -> str:
    """Brain session id for this update (see _extract_session_ref)."""
    return _extract_session_ref(update).session_id


def _clean_message_text(text: str) -> str:
    """Remove @bot mentions from message text."""
    if BOT_USERNAME:
        text = re.sub(rf"@{re.escape(BOT_USERNAME)}\s*", "", text)
    return text.strip()


# ── Streaming support (SQLite event queue) ────────────────

def _get_stream_db():
    """Get/create the stream_events table for Telegram streaming."""
    import sqlite3
    from ..config import DATA_DIR
    db_path = DATA_DIR / "nally.db"
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS stream_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT,
            created_at REAL NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_stream_session ON stream_events(session_id, id)
    """)
    return conn


def _write_stream_event(session_id: str, event_type: str, payload: str):
    """Write a streaming event to SQLite (called from web server process)."""
    import time as _time
    try:
        conn = _get_stream_db()
        conn.execute(
            "INSERT INTO stream_events (session_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            (session_id, event_type, payload, _time.time()),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _read_stream_events(session_id: str, after_id: int = 0) -> list:
    """Read unprocessed stream events for a session (called from bot process)."""
    try:
        conn = _get_stream_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, event_type, payload FROM stream_events WHERE session_id = ? AND id > ? ORDER BY id",
            (session_id, after_id),
        )
        rows = cursor.fetchall()
        conn.close()
        return rows
    except Exception:
        return []


def _clear_stream_events(session_id: str):
    """Clear old stream events for a session."""
    try:
        conn = _get_stream_db()
        conn.execute("DELETE FROM stream_events WHERE session_id = ?", (session_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass


# ── Callback ID map (SQLite persistence for cross-process resolve) ──

def _get_callback_db():
    """Get/create the callback_id_map table for cross-process truncation resolve."""
    import sqlite3
    from ..config import DATA_DIR
    db_path = DATA_DIR / "nally.db"
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS callback_id_map (
            safe_id TEXT PRIMARY KEY,
            full_id TEXT NOT NULL,
            created_at REAL NOT NULL
        )
    """)
    return conn


def _write_callback_map(safe_id: str, full_id: str):
    """Persist safe->full mapping to SQLite (cross-process)."""
    import time as _time
    try:
        conn = _get_callback_db()
        conn.execute(
            "INSERT OR REPLACE INTO callback_id_map (safe_id, full_id, created_at) VALUES (?, ?, ?)",
            (safe_id, full_id, _time.time()),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


def _read_callback_map(safe_id: str) -> Optional[str]:
    """Read full_id for safe_id from SQLite. Returns None if missing."""
    try:
        conn = _get_callback_db()
        cursor = conn.cursor()
        cursor.execute("SELECT full_id FROM callback_id_map WHERE safe_id = ?", (safe_id,))
        row = cursor.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None


def _clear_old_callbacks(max_age: float = 3600):
    """Remove callback mappings older than max_age seconds (cleanup)."""
    import time as _time
    try:
        conn = _get_callback_db()
        conn.execute("DELETE FROM callback_id_map WHERE created_at < ?", (_time.time() - max_age,))
        conn.commit()
        conn.close()
    except Exception:
        pass


def _make_emit(chat_id: int):
    """Create an emit callback that sends approval requests as inline buttons."""
    loop = asyncio.get_running_loop()

    def emit(event: str, data: dict):
        if event != "confirmation_required":
            return

        from telegram import InlineKeyboardButton, InlineKeyboardMarkup

        tc_id = data["tool_call_id"]
        tool = data["name"]
        args = data.get("args", {})
        args_str = " ".join(f"{k}={v}" for k, v in args.items()) if args else ""

        def _esc(s: str) -> str:
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        text = f"<b>Permission required</b>\n\n<b>Tool:</b> <code>{_esc(tool)}</code>"
        if args_str:
            text += f"\n<b>Args:</b> <code>{_esc(args_str[:500])}</code>"
        if data.get("diff"):
            diff = data["diff"][:800]
            text += f"\n\n<pre>{_esc(diff)}</pre>"

        # Telegram callback_data max is 64 bytes — truncate tc_id if needed
        # and store full mapping so approval_callback can look it up
        MAX_CB_DATA = 60  # leave room for "approve:" prefix
        cb_prefix = "approve:"
        max_tc_len = MAX_CB_DATA - len(cb_prefix)
        safe_tc_id = tc_id[:max_tc_len] if len(tc_id) > max_tc_len else tc_id

        approve_cb = f"approve:{safe_tc_id}"
        deny_cb = f"deny:{safe_tc_id}"

        # Always store mapping so callback handler can resolve IDs
        with _callback_id_lock:
            _callback_id_map[safe_tc_id] = tc_id
        # Persist for cross-process (web server -> bot) resolution
        _write_callback_map(safe_tc_id, tc_id)
        logger.info(f"DEBUG CB: tc_id={tc_id!r} ({len(tc_id)} chars), safe={safe_tc_id!r} ({len(safe_tc_id)} chars)")
        logger.info(f"DEBUG CB: approve_cb={approve_cb!r} ({len(approve_cb.encode('utf-8'))} bytes)")
        logger.info(f"DEBUG CB: _callback_id_map has {len(_callback_id_map)} entries after storing {safe_tc_id!r}")

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Approve", callback_data=f"approve:{safe_tc_id}"),
            InlineKeyboardButton("Deny", callback_data=f"deny:{safe_tc_id}"),
        ]])

        try:
            if BOT:
                print(f"[DEBUG-APP] emit sending via BOT id={id(BOT)}", flush=True)
                async def _do_send():
                    try:
                        await _send_with_retry(
                            BOT.send_message, chat_id, text,
                            parse_mode="HTML", reply_markup=keyboard,
                        )
                        logger.info(f"Approval message sent for tool_call_id={tc_id}")
                    except Exception as e:
                        logger.error(f"Approval message failed after {_TG_MAX_RETRIES} attempts: {e}")
                asyncio.run_coroutine_threadsafe(_do_send(), loop)
            else:
                logger.warning("Approval emit: BOT is None, cannot send approval message")
        except Exception as e:
            logger.error(f"Approval emit failed: {e}")

    return emit


def _make_emit_standalone(chat_id: int, session_id: str = ""):
    """Emit callback for the web-server process.

    Used when the bot runs as a separate process: the web server owns the
    agent + approval gate, so the approval button is sent directly from the
    web server via its own Bot client. Streaming events (response chunks,
    thoughts) are written to SQLite so the bot process can poll and edit
    the Telegram message progressively.
    """
    loop = asyncio.get_running_loop()

    def emit(event: str, data: dict):
        # Write ALL streaming events to SQLite for the bot process to pick up.
        # confirmation_required is included so the bot can edit the placeholder
        # message inline — instead of sending a NEW message each time (which
        # caused messages to pile up in Telegram).
        if event in ("response", "thought", "tool_call", "system_notice",
                     "confirmation_required", "final_response") and session_id:
            try:
                import json as _json
                _write_stream_event(session_id, event, _json.dumps(data))
            except Exception:
                pass

        if event != "confirmation_required":
            return

        # Store callback mapping so approval_callback can resolve the button
        # press back to the full tool_call_id (cross-process via SQLite).
        tc_id = data.get("tool_call_id", "")
        MAX_CB_DATA = 60  # leave room for "approve:" prefix
        cb_prefix = "approve:"
        max_tc_len = MAX_CB_DATA - len(cb_prefix)
        safe_tc_id = tc_id[:max_tc_len] if len(tc_id) > max_tc_len else tc_id

        with _callback_id_lock:
            _callback_id_map[safe_tc_id] = tc_id
        _write_callback_map(safe_tc_id, tc_id)
        logger.info(f"Approval request queued via stream events for tool_call_id={tc_id}")

    return emit


# Maps truncated callback_data IDs back to full tool_call_ids
_callback_id_map: dict = {}
# Written from the tool-executor worker thread (via emit) and read from the
# bot's event loop (approval_callback) — guard against iteration races.
_callback_id_lock = threading.Lock()


async def approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Approve/Deny button presses for permission gates."""
    query = update.callback_query

    if not query or not query.data:
        logger.warning("approval_callback: no query or query.data")
        return

    logger.info(f"DEBUG CALLBACK: received data={query.data!r}, len={len(query.data)} bytes")
    logger.info(f"DEBUG CALLBACK: query.id={query.id}, chat={query.message.chat_id if query.message else '?'}")
    logger.info(f"DEBUG CALLBACK: _callback_id_map={dict(_callback_id_map)}")

    # Acknowledge the callback — show loading spinner then toast
    for _attempt in range(3):
        try:
            await query.answer()
            logger.info(f"DEBUG CALLBACK: query.answer() succeeded on attempt {_attempt+1}")
            break
        except Exception as e:
            logger.warning(f"query.answer() attempt {_attempt+1} failed: {e}")
            if _attempt < 2:
                await asyncio.sleep(min(2 ** (_attempt + 1), 5))
            else:
                logger.error(f"query.answer() failed after 3 attempts: {e}")

    data = query.data
    if data.startswith("approve:") or data.startswith("deny:"):
        cb_id = data.split(":", 1)[1]
        approved = data.startswith("approve:")
        # Resolve truncated callback_data IDs back to full tool_call_ids
        # Check in-memory first, then SQLite (cross-process), then fallback to raw cb_id
        with _callback_id_lock:
            full_tc_id = _callback_id_map.get(cb_id)
        if not full_tc_id:
            full_tc_id = _read_callback_map(cb_id)
        if not full_tc_id:
            full_tc_id = cb_id
        logger.info(f"DEBUG CALLBACK: cb_id={cb_id!r}, resolved to full_tc_id={full_tc_id!r}, approved={approved}")
        logger.info(f"DEBUG CALLBACK: _callback_id_map contains: {list(_callback_id_map.keys())}")
        # Resolve in BOTH processes so approvals work regardless of which
        # process owns the agent/approval gate:
        #  - locally: handles the voice path, where the gate runs in this
        #    (bot) process.
        #  - via HTTP to the web server: handles the text path, where the gate
        #    runs in the web-server process (the bot now forwards there).
        from nally.agent.graph import resolve_approval as _local_resolve

        # Local resolve covers the voice path (agent gate runs in this bot
        # process). Runs off the loop because it does blocking SQLite I/O.
        await asyncio.to_thread(_local_resolve, full_tc_id, approved)

        import httpx

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(
                    f"{_web_base_url()}/api/telegram/approve",
                    json={"tc_id": full_tc_id, "approved": approved},
                )
                if resp.status_code == 200:
                    resolved = resp.json().get("resolved", False)
                else:
                    logger.warning(f"Approval HTTP returned {resp.status_code}")
                    resolved = False
        except Exception as e:
            logger.error(f"Approval HTTP failed: {e}")
            resolved = False
        logger.info(f"DEBUG CALLBACK: resolve_approval returned {resolved}")

        if not resolved:
            try:
                await query.edit_message_text(
                    "This approval request already expired. Please send your request again.",
                )
            except Exception as e:
                logger.error(f"approval_callback: edit expired message failed: {e}")
            return

        if query.message is not None:
            status_text = "✅ <b>Approved</b>" if approved else "❌ <b>Denied</b>"
            try:
                orig_text = query.message.text_html or query.message.text or ""
                await query.edit_message_text(
                    f"{orig_text}\n\n<b>Result:</b> {status_text}",
                    parse_mode="HTML"
                )
                logger.info(f"approval_callback: message updated for tc_id={full_tc_id}")
            except Exception as e:
                logger.warning(f"approval_callback: edit_message_text failed: {e}")
                try:
                    await context.bot.send_message(
                        chat_id=query.message.chat_id,
                        text=f"{status_text}",
                        parse_mode="HTML"
                    )
                except Exception as e2:
                    logger.error(f"approval_callback: fallback send_message also failed: {e2}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "Hey! I'm Nally.\n\n"
        "Send me text or voice messages and I'll respond.\n"
        "In groups, mention me with @NallyFirstbot."
    )


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command — show system health."""
    import time
    from ..config import ACTIVE_MODEL, DAILY_TOKEN_BUDGET, PROVIDER

    # Uptime
    uptime = time.time() - _start_time
    days = int(uptime // 86400)
    hours = int((uptime % 86400) // 3600)
    minutes = int((uptime % 3600) // 60)
    uptime_str = f"{days}d {hours}h {minutes}m" if days else f"{hours}h {minutes}m"

    # Token budget
    try:
        from ..agent.context import context_manager
        stats = context_manager.get_stats()
        daily_used = stats.get("daily_tokens", 0)
        budget = stats.get("daily_token_budget", 0)
        budget_line = f"Token budget: {daily_used:,}/{budget:,} used" if budget > 0 else "Token budget: unlimited"
    except Exception:
        budget_line = "Token budget: unavailable"

    # Tools
    try:
        from ..tools.registry import registry
        tool_count = len(registry.tools)
    except Exception:
        tool_count = 0

    # DB size
    try:
        from ..config import DATA_DIR
        db_path = DATA_DIR / "nally_memory.db"
        db_size = f"{db_path.stat().st_size / 1024:.0f}KB" if db_path.exists() else "new"
    except Exception:
        db_size = "unknown"

    await update.message.reply_text(
        f"Nally Status\n"
        f"─────────────\n"
        f"Provider: {PROVIDER}\n"
        f"Model: {ACTIVE_MODEL}\n"
        f"Uptime: {uptime_str}\n"
        f"Tools: {tool_count} loaded\n"
        f"DB: {db_size}\n"
        f"{budget_line}"
    )


async def abort_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /abort command — cancel running operations (per-route)."""
    from ..core.abort import set_abort

    ref = _extract_session_ref(update)
    set_abort(ref.route_key)
    await update.message.reply_text("Abort signal sent. I'll stop what I'm doing.")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages.

    The bot runs as a separate process: it forwards the message to the web
    server (which owns the agent + approval gate) over HTTP and relays the
    reply back to Telegram. This keeps the bot's event loop free for polling
    and avoids the cross-process thread-pool deadlock in the approval gate.
    """
    message = update.message
    if not message or not message.text:
        return

    chat = update.effective_chat
    text = message.text

    # Beta: handle all group messages, not just @mentions (full Telegram capabilities)
    # Keep mention cleaning if present, but don't require it
    if chat.type in ("group", "supergroup"):
        text = _clean_message_text(text)
        if not text:
            # Ignore empty after cleaning (e.g., just an @mention)
            return

    ref = _extract_session_ref(update)
    session_id = ref.session_id
    route_key = ref.route_key

    # Text "abort" fallback — same as /abort command (per-route)
    if text.strip().lower() == "abort":
        from ..core.abort import set_abort
        set_abort(route_key)
        await message.reply_text("Abort signal sent. I'll stop what I'm doing.")
        return

    try:
        await chat.send_chat_action("typing")
    except Exception:
        pass

    import httpx

    # Send placeholder message for progressive editing
    try:
        sent_msg = await _send_with_retry(message.reply_text, "Thinking...")
    except Exception:
        sent_msg = None

    # Clear old stream events for this session (per-route)
    _clear_stream_events(route_key)

    # Fire HTTP request to web server (fire-and-forget — just triggers processing).
    # The response comes back via stream events (final_response), not the HTTP body.
    # This avoids Render proxy 502/520 timeouts when the agent takes a long time
    # (e.g. waiting for bridge approval).
    async def _do_request():
        import json as _json
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                resp = await client.post(
                    f"{_web_base_url()}/api/telegram/message",
                    json={"session_id": session_id, "route_key": route_key, "text": text, "chat_id": chat.id},
                )
                if resp.status_code != 200:
                    _write_stream_event(route_key, "final_response",
                        _json.dumps({"text": f"Web server error (HTTP {resp.status_code})"}))
            except Exception as e:
                logger.error(f"HTTP to web server failed: {type(e).__name__}: {e}")
                _write_stream_event(route_key, "final_response",
                    _json.dumps({"text": f"Web server unreachable: {e}"}))

    import json as _json_mod
    request_task = asyncio.create_task(_do_request())

    # Poll stream events for the final response (and approval requests).
    # The web server processes in the background and writes events to SQLite.
    last_event_id = 0
    collected_text = ""
    final_response = None
    _deadline = time.time() + 300.0  # 5-minute overall timeout
    _showing_approval = False  # True while approval buttons are displayed

    while final_response is None and time.time() < _deadline:
        await asyncio.sleep(2)
        events = _read_stream_events(route_key, after_id=last_event_id)
        for eid, etype, payload in events:
            last_event_id = eid
            try:
                data = _json_mod.loads(payload) if payload else {}
            except Exception:
                data = {}
            if etype == "final_response":
                final_response = data.get("text", "")
            elif etype == "response":
                chunk_text = data.get("text", "")
                if chunk_text:
                    collected_text = chunk_text
                    _showing_approval = False
            elif etype == "tool_call":
                tool_name = data.get("name", "?")
                collected_text = f"Using {tool_name}..."
                _showing_approval = False
            elif etype == "confirmation_required":
                # Edit the placeholder inline with the approval request + buttons
                # instead of sending a new message (fixes message pile-up).
                tc_id = data.get("tool_call_id", "")
                tool = data.get("name", "?")
                args = data.get("args", {})
                args_str = " ".join(f"{k}={v}" for k, v in args.items()) if args else ""

                def _esc(s: str) -> str:
                    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

                appr_text = f"<b>Permission required</b>\n\n<b>Tool:</b> <code>{_esc(tool)}</code>"
                if args_str:
                    appr_text += f"\n<b>Args:</b> <code>{_esc(args_str[:500])}</code>"

                # Build inline keyboard (callback_data resolves via _callback_id_map)
                from telegram import InlineKeyboardButton, InlineKeyboardMarkup
                MAX_CB_DATA = 60
                max_tc_len = MAX_CB_DATA - len("approve:")
                safe_tc_id = tc_id[:max_tc_len] if len(tc_id) > max_tc_len else tc_id
                with _callback_id_lock:
                    _callback_id_map[safe_tc_id] = tc_id
                _write_callback_map(safe_tc_id, tc_id)

                keyboard = InlineKeyboardMarkup([[
                    InlineKeyboardButton("Approve", callback_data=f"approve:{safe_tc_id}"),
                    InlineKeyboardButton("Deny", callback_data=f"deny:{safe_tc_id}"),
                ]])

                if sent_msg:
                    try:
                        await sent_msg.edit_text(appr_text[:4000], parse_mode="HTML", reply_markup=keyboard)
                        _showing_approval = True
                    except Exception as e:
                        logger.warning(f"Failed to edit placeholder for approval: {e}")

        # Edit placeholder with latest status (skip while showing approval buttons)
        if sent_msg and collected_text and not _showing_approval:
            try:
                html_text = md_to_telegram_html(collected_text)
                await sent_msg.edit_text(html_text[:4000], parse_mode="HTML")
            except Exception:
                try:
                    await sent_msg.edit_text(collected_text[:4000])
                except Exception:
                    pass

    # Cancel the HTTP task if still running (fire-and-forget)
    if not request_task.done():
        request_task.cancel()

    _clear_stream_events(route_key)

    response = final_response
    if response is None:
        response = "Request timed out after 5 minutes. Try a simpler task or say 'continue'."

    if not response or response == "__EXIT__":
        return

    text_response = response.get("text", "") if isinstance(response, dict) else response

    # Outbound file markers (IMAGE_FILE: / SEND_FILE:) — send as Telegram attachments
    try:
        from .media import parse_outbound_files, strip_file_markers, send_attachments_bot
        out_files = parse_outbound_files(text_response if isinstance(text_response, str) else str(text_response))
        if out_files:
            cleaned = strip_file_markers(text_response)
            if not cleaned.strip():
                cleaned = "Here you go:"
            text_response = cleaned
    except Exception as e:
        logger.debug(f"Bot outbound media parse failed: {e}")
        out_files = []

    final_html = md_to_telegram_html(text_response)

    # Final edit of the placeholder message with the complete response
    if sent_msg:
        _edit_ok = False
        try:
            await sent_msg.edit_text(final_html[:4000], parse_mode="HTML", reply_markup=None)
            _edit_ok = True
        except Exception:
            try:
                await sent_msg.edit_text(text_response[:4000], reply_markup=None)
                _edit_ok = True
            except Exception:
                sent_msg = None
                _edit_ok = False
        if _edit_ok:
            if out_files:
                try:
                    await send_attachments_bot(context.bot, chat.id, out_files)
                except Exception as e:
                    logger.error(f"Bot send attachments failed: {e}")
            return

    # Fallback: send as new messages if edit failed or no placeholder
    chunks = _split_message(final_html)
    for chunk in chunks:
        try:
            await _send_with_retry(message.reply_text, chunk, parse_mode="HTML")
        except Exception:
            try:
                await _send_with_retry(message.reply_text, chunk)
            except Exception as e:
                logger.error(f"Telegram reply failed: {e}")
    if out_files:
        try:
            await send_attachments_bot(context.bot, chat.id, out_files)
        except Exception as e:
            logger.error(f"Bot send attachments fallback failed: {e}")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming voice messages (STT -> agent -> reply)."""
    message = update.message
    if not message or not message.voice:
        return

    chat = update.effective_chat
    ref = _extract_session_ref(update)
    session_id = ref.session_id
    route_key = ref.route_key

    # Check if ffmpeg is available
    from .voice import check_ffmpeg
    if not check_ffmpeg():
        await message.reply_text("Voice not available — ffmpeg not installed.")
        return

    # Show typing indicator (best-effort: a failure here must not abort the reply)
    try:
        await chat.send_chat_action("typing")
    except Exception:
        logger.debug("Failed to send typing indicator")

    try:
        # Download voice file from Telegram
        voice_file = await message.voice.get_file()
        ogg_bytes = await voice_file.download_as_bytearray()

        # Convert OGG/Opus to raw PCM for STT
        from .voice import ogg_to_pcm
        pcm_bytes = ogg_to_pcm(bytes(ogg_bytes))
        if not pcm_bytes:
            await message.reply_text("Could not process voice message.")
            return

        # Transcribe with Whisper
        from ..voice.stt import transcribe
        text = await asyncio.to_thread(transcribe, pcm_bytes)

        if not text.strip():
            await message.reply_text("Couldn't understand the voice message.")
            return

        # Process through agent (per-route isolated history, same brain)
        emit = _make_emit(chat.id)
        if not callable(emit):
            logger.error(f"_make_emit failed to return a callable emit callback (got {emit!r})")
            emit = None
        response = await asyncio.to_thread(session_manager.process, session_id, text, emit=emit, route_key=route_key)

        if not response or response == "__EXIT__":
            return

        # Extract text from structured response
        if isinstance(response, dict):
            text_response = response.get("text", "")
        else:
            text_response = response

        # Always send voice response for voice input
        await _send_voice_response(message, text_response)

        # If agent also produced files (e.g. image gen via voice), send them
        try:
            from .media import parse_outbound_files, send_attachments_bot, strip_file_markers
            out_files = parse_outbound_files(text_response if isinstance(text_response, str) else str(text_response))
            if out_files:
                await send_attachments_bot(context.bot, chat.id, out_files)
        except Exception as e:
            logger.debug(f"Voice outbound file send failed: {e}")

    except Exception as e:
        logger.error(f"Telegram voice error: {e}")
        try:
            await _send_with_retry(message.reply_text, f"Voice processing failed: {e}")
        except Exception:
            logger.error("Telegram voice error reply failed after retries")


async def handle_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming photos/documents (download -> agent -> reply with files)."""
    message = update.message
    if not message:
        return
    # Only photo or document
    if not (message.photo or message.document):
        return

    chat = update.effective_chat
    ref = _extract_session_ref(update)
    session_id = ref.session_id
    route_key = ref.route_key

    # Beta: handle all group media, mention optional
    caption = message.caption or message.text or ""
    if chat.type in ("group", "supergroup"):
        caption = _clean_message_text(caption)
        # caption may be empty — still process file with description

    # Text "abort" fallback (per-route)
    if caption.strip().lower() == "abort":
        from ..core.abort import set_abort
        set_abort(route_key)
        await message.reply_text("Abort signal sent. I'll stop what I'm doing.")
        return

    try:
        await chat.send_chat_action("typing")
    except Exception:
        pass

    import httpx

    # Download media to inbox and build combined prompt
    combined = caption
    try:
        from .media import save_bot_media, build_agent_input, analyze_image_for_game
        saved_path, media_desc = await save_bot_media(context.bot, message, ref.route_key)
        if saved_path and saved_path.suffix.lower() in {".jpg",".jpeg",".png",".webp",".gif",".bmp"}:
            try:
                # Game-aware vision + OCR (uses Muse Spark vision when available)
                vision_block = await analyze_image_for_game(saved_path, user_question=caption)
                if vision_block:
                    media_desc += f"\n\n{vision_block}\n\n[Instruction: Use the Vision analysis above as the primary source. Do not run PIL/code to re-analyze the image — answer directly from Vision. This is the authoritative description.]"
                    # Record a receipt so the claim verifier sees this as grounded
                    try:
                        from nally.tools.receipts import receipt_store
                        import uuid
                        receipt_store.record(
                            tool_call_id=f"vision_{uuid.uuid4().hex[:8]}",
                            tool="vision_analyze",
                            args={"image": str(saved_path), "question": caption[:200]},
                            result=vision_block[:2000],
                            success=True,
                            duration_ms=1500,
                        )
                    except Exception:
                        pass
            except Exception as e:
                logger.debug(f"Bot vision analyze failed: {e}")
        combined = build_agent_input(caption, media_desc)
        if not combined.strip():
            combined = media_desc or "[User sent a file]"
    except Exception as e:
        logger.error(f"Bot media download failed: {e}")
        combined = caption or "[User sent a file — download failed]"
        if not combined.strip():
            await message.reply_text("Failed to process that file.")
            return

    # Progressive placeholder
    try:
        sent_msg = await _send_with_retry(message.reply_text, "Thinking...")
    except Exception:
        sent_msg = None

    _clear_stream_events(route_key)

    async def _do_request():
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                f"{_web_base_url()}/api/telegram/message",
                json={"session_id": session_id, "route_key": route_key, "text": combined, "chat_id": chat.id},
            )
            if resp.status_code != 200:
                return f"Web server error (HTTP {resp.status_code})"
            return resp.json().get("response", "")

    request_task = asyncio.create_task(_do_request())
    last_event_id = 0
    collected_text = ""
    while not request_task.done():
        await asyncio.sleep(2)
        events = _read_stream_events(route_key, after_id=last_event_id)
        for eid, etype, payload in events:
            last_event_id = eid
            try:
                import json as _json
                data = _json.loads(payload) if payload else {}
            except Exception:
                data = {}
            if etype == "response":
                chunk_text = data.get("text", "")
                if chunk_text:
                    collected_text = chunk_text
            elif etype == "tool_call":
                tool_name = data.get("name", "?")
                collected_text = f"Using {tool_name}..."
        if sent_msg and collected_text:
            try:
                html_text = md_to_telegram_html(collected_text)
                await sent_msg.edit_text(html_text[:4000], parse_mode="HTML")
            except Exception:
                try:
                    await sent_msg.edit_text(collected_text[:4000])
                except Exception:
                    pass

    try:
        response = request_task.result()
    except Exception as e:
        logger.error(f"HTTP to web server failed (media): {e}")
        response = f"Web server unreachable: {e}"

    _clear_stream_events(route_key)

    if not response or response == "__EXIT__":
        return

    text_response = response.get("text", "") if isinstance(response, dict) else response

    # Outbound files
    try:
        from .media import parse_outbound_files, strip_file_markers, send_attachments_bot
        out_files = parse_outbound_files(text_response if isinstance(text_response, str) else str(text_response))
        if out_files:
            cleaned = strip_file_markers(text_response)
            if not cleaned.strip():
                cleaned = "Here you go:"
            text_response = cleaned
    except Exception as e:
        logger.debug(f"Bot media outbound parse failed: {e}")
        out_files = []

    final_html = md_to_telegram_html(text_response)
    if sent_msg:
        _edit_ok = False
        try:
            await sent_msg.edit_text(final_html[:4000], parse_mode="HTML")
            _edit_ok = True
        except Exception:
            try:
                await sent_msg.edit_text(text_response[:4000])
                _edit_ok = True
            except Exception:
                sent_msg = None
                _edit_ok = False
        if _edit_ok:
            if out_files:
                try:
                    await send_attachments_bot(context.bot, chat.id, out_files)
                except Exception as e:
                    logger.error(f"Bot send attachments (media) failed: {e}")
            return

    chunks = _split_message(final_html)
    for chunk in chunks:
        try:
            await _send_with_retry(message.reply_text, chunk, parse_mode="HTML")
        except Exception:
            try:
                await _send_with_retry(message.reply_text, chunk)
            except Exception as e:
                logger.error(f"Telegram media reply failed: {e}")
    if out_files:
        try:
            await send_attachments_bot(context.bot, chat.id, out_files)
        except Exception as e:
            logger.error(f"Bot send attachments fallback (media) failed: {e}")


async def _send_voice_response(message, text: str):
    """Send a voice response (LLM summary -> TTS -> OGG -> Telegram voice message)."""
    try:
        from ..voice.formatter import VoiceFormatter, VoiceMode
        from ..voice.tts import synthesize_to_wav
        from .voice import wav_to_ogg

        # Generate voice summary via lightweight LLM
        voice_summary = await _generate_voice_summary(text)

        # Format for speech (strip code, tables, etc.)
        formatter = VoiceFormatter()
        speak_text = formatter.format(text, mode=VoiceMode.SMART, summary=voice_summary)

        if not speak_text:
            await _send_with_retry(message.reply_text, md_to_telegram_html(text), parse_mode="HTML")
            return

        # Synthesize to WAV, then convert to OGG
        wav_bytes = await asyncio.to_thread(synthesize_to_wav, speak_text)
        if not wav_bytes:
            # Fallback to text
            await _send_with_retry(message.reply_text, md_to_telegram_html(text), parse_mode="HTML")
            return

        ogg_bytes = await asyncio.to_thread(wav_to_ogg, wav_bytes)
        if not ogg_bytes:
            # Fallback to text
            await _send_with_retry(message.reply_text, md_to_telegram_html(text), parse_mode="HTML")
            return

        # Send as Telegram voice message with full text as caption
        audio_file = io.BytesIO(ogg_bytes)
        audio_file.name = "nally_voice.ogg"
        caption = md_to_telegram_html(text[:1024]) if len(text) > 100 else None
        try:
            await _send_with_retry(message.reply_voice, voice=audio_file, caption=caption)
        except Exception:
            logger.error("Telegram voice send failed after retries — falling back to text")
            await _send_with_retry(message.reply_text, md_to_telegram_html(text), parse_mode="HTML")

    except Exception as e:
        logger.error(f"Voice response failed: {e}")
        # Fallback to text
        try:
            await _send_with_retry(message.reply_text, md_to_telegram_html(text), parse_mode="HTML")
        except Exception:
            logger.error("Telegram voice fallback text send failed after retries")


async def _generate_voice_summary(text: str) -> str:
    """Generate a 1-2 sentence voice summary using the main LLM."""
    try:
        if len(text) <= 200:
            return text

        from ..agent.llm import llm

        summary_response = await asyncio.to_thread(
            llm.simple_chat,
            user_message=f"Rewrite this as a 1-2 sentence spoken summary. Keep it conversational and natural, like you're talking to a friend. No markdown, no lists, just flowing speech:\n\n{text}",
            system_prompt="You are a voice assistant. Rewrite responses for natural spoken delivery. Be conversational, warm, concise. Never use markdown, bullet points, or lists. Just flowing sentences.",
        )
        return summary_response.strip()
    except Exception as e:
        logger.warning(f"Voice summary generation failed: {e}")
        # Fallback: first 2 sentences
        import re
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        if len(sentences) >= 2:
            return " ".join(sentences[:2])
        elif sentences:
            return sentences[0]
        return text[:200]


async def error_handler(update: Optional[Update], context: ContextTypes.DEFAULT_TYPE):
    """Log errors from the telegram bot — collapse DNS 11001 to one warning."""
    from telegram.error import TimedOut, NetworkError
    error = context.error
    err_str = str(error) if error else ""
    # DNS / network down — already filtered to one warning every 30s, just log compactly
    if "getaddrinfo failed" in err_str or "11001" in err_str or "WinError 1231" in err_str or "WinError 1236" in err_str:
        logger.warning(f"Telegram DNS/network down (will retry): {err_str[:120]}")
        return
    if isinstance(error, TimedOut):
        logger.warning(f"Telegram bot timeout: {error} (likely slow agent response)")
    elif isinstance(error, NetworkError):
        logger.warning(f"Telegram network error (retrying): {error}")
    else:
        logger.error(f"Telegram bot error: {error}")


def create_bot_app(token: str, webhook_url: Optional[str] = None) -> Application:
    """Create and configure the Telegram bot application.

    Args:
        token: Telegram bot token
        webhook_url: If set, use webhook mode. If None, use polling.
    """
    global BOT_USERNAME

    if webhook_url:
        logger.info(f"create_bot_app: webhook_url provided ({webhook_url}) — callers must register the webhook")

    request = HTTPXRequest(
        connection_pool_size=100,
        connect_timeout=30.0,
        read_timeout=30.0,
        write_timeout=30.0,
        pool_timeout=30.0,
    )

    app = (
        Application.builder()
        .token(token)
        .request(request)
        .concurrent_updates(True)
        .build()
    )

    # Store bot username and bot reference for mention detection and approval messages
    async def post_init(application: Application):
        global BOT_USERNAME, BOT
        # Quick DNS check before get_me — gives actionable hint vs 20-line traceback
        try:
            import socket as _socket
            _socket.getaddrinfo("api.telegram.org", 443, timeout=3)
        except Exception as _dns_e:
            logger.warning(f"DNS check failed for api.telegram.org at startup: {_dns_e} — check internet/DNS/proxy. Will retry get_me…")

        for _attempt in range(3):
            try:
                me = await application.bot.get_me()
                BOT_USERNAME = me.username
                BOT = application.bot
                logger.info(f"Telegram bot started: @{BOT_USERNAME}")
                break
            except Exception as e:
                err_str = str(e)
                is_dns = "getaddrinfo failed" in err_str or "11001" in err_str or "WinError 1231" in err_str
                level = logger.warning if is_dns else logger.error
                msg = f"Telegram bot get_me() failed at startup (attempt {_attempt+1}/3): {e}"
                if is_dns:
                    msg += " — DNS/network down, will retry polling anyway"
                # Don't take the whole bot down; be loud so operators notice degraded state
                print(f"[{'WARN' if is_dns else 'ERROR'}] {msg}")
                level(msg)
                if _attempt < 2:
                    await asyncio.sleep(2 ** (_attempt + 1))
                else:
                    # Final failure — leave BOT as None, polling will still retry getUpdates
                    BOT = application.bot  # allow approval emit to at least try
                    BOT_USERNAME = None

    app.post_init = post_init

    # DEBUG: print app instance ID to verify same instance is used everywhere
    print(f"[DEBUG-APP] create_bot_app returned app id={id(app)}", flush=True)

    # Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("abort", abort_command))

    # DEBUG: catch-all callback logger (group=-1 = runs first, doesn't consume)
    async def _debug_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        print(f"[DEBUG-CB] RAW CALLBACK: data={q.data!r} query_id={q.id}", flush=True)
        logger.info(f"DEBUG-CB: RAW data={q.data!r} query_id={q.id}")

    app.add_handler(CallbackQueryHandler(_debug_cb), group=-1)

    # Permission gate inline buttons
    app.add_handler(CallbackQueryHandler(approval_callback, pattern=r"^(approve|deny):"), group=0)

    # Voice messages (STT)
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))

    # Photos / documents (with caption handling)
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_media))

    # Text messages
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            handle_message,
        )
    )
    app.add_error_handler(error_handler)

    return app


def run_telegram_bot(polling: bool = True, webhook_url: Optional[str] = None):
    """Start the Telegram bot.

    Args:
        polling: Use polling mode (default, good for dev)
        webhook_url: Webhook URL for production mode

    When called from a daemon thread, creates its own event loop via asyncio.run()
    so the bot's HTTPX connection pool is fully isolated from the web server's loop.
    Uses manual async steps instead of run_polling() which requires signal handlers
    (only available in the main thread).
    """
    import asyncio

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("[FATAL] TELEGRAM_BOT_TOKEN not set in .env — cannot start Telegram bot")
        logger.error("TELEGRAM_BOT_TOKEN not set in .env")
        return

    async def _run_bot():
        app = create_bot_app(token, webhook_url)
        try:
            await app.initialize()
            if app.post_init:
                await app.post_init(app)
            await app.start()
            if polling:
                await app.updater.start_polling(
                    # drop_pending_updates=True deletes any leftover webhook before
                    # polling — a stale webhook causes getUpdates to 409 and the bot
                    # silently receives no updates.
                    drop_pending_updates=True,
                    bootstrap_retries=5,
                    allowed_updates=None,
                )
                logger.info("Telegram bot started (polling, isolated thread)")
            elif webhook_url:
                webhook_path = f"/telegram/webhook/{token}"
                full_webhook_url = f"{webhook_url.rstrip('/')}{webhook_path}"
                await app.bot.set_webhook(
                    url=full_webhook_url,
                    allowed_updates=[UpdateType.MESSAGE, UpdateType.CALLBACK_QUERY],
                )
                logger.info(f"Telegram bot started (webhook mode) -> {full_webhook_url}")
            else:
                logger.error(
                    "run_telegram_bot: polling=False requires a webhook_url. "
                    "Telegram bot did not start."
                )
                return
            try:
                while True:
                    await asyncio.sleep(1)
            except (KeyboardInterrupt, asyncio.CancelledError):
                pass
            finally:
                try:
                    await app.stop()
                except Exception:
                    pass
                try:
                    await app.shutdown()
                except Exception:
                    pass
        except Exception as e:
            print(f"[FATAL] Telegram bot startup failed: {e}")
            logger.error(f"Telegram bot startup failed: {e}")
            try:
                await app.shutdown()
            except Exception:
                pass

    asyncio.run(_run_bot())


async def start_telegram_polling() -> Optional[Application]:
    """Telegram bot runs as a separate process (run_bot_standalone.py).

    The web server no longer starts the bot inline. The bot polls Telegram in
    its own process with its own event loop and forwards messages/approvals to
    this server over HTTP. This avoids the PTB v21 daemon-thread event-loop
    issues and the cross-process thread-pool deadlock in the approval gate.
    """
    logger.info("Telegram bot runs as a separate process — skipping inline start")
    return None


async def stop_telegram_polling(app: Optional[Application]):
    """Gracefully stop a polling Application started by start_telegram_polling.

    Awaits the update_fetcher task (which is what prevents the
    "Task was destroyed but it is pending!" warning on teardown).
    """
    if not app:
        return
    try:
        if app.updater.running:
            await app.updater.stop()
        if app.running:
            await app.stop()
        await app.shutdown()
        logger.info("Telegram bot stopped (polling)")
    except Exception as e:
        logger.error(f"Telegram bot shutdown failed: {e}")


async def start_telegram_webhook(webhook_base_url: str):
    """Start Telegram bot in webhook mode and register with Telegram API.

    Called from FastAPI lifespan when running with --telegram flag.
    webhook_base_url: e.g. "https://your-domain.com" or "http://localhost:5000"
    """
    global BOT, BOT_USERNAME

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not set — Telegram webhook not started")
        return None

    app = create_bot_app(token, webhook_base_url)

    # Initialize the application (sets BOT via post_init)
    await app.initialize()
    await app.start()

    # Register webhook with Telegram
    webhook_path = f"/telegram/webhook/{token}"
    full_webhook_url = f"{webhook_base_url.rstrip('/')}{webhook_path}"

    await app.bot.set_webhook(
        url=full_webhook_url,
        allowed_updates=[
            "message",
            "callback_query",
        ],
    )
    logger.info(f"Telegram webhook set: {full_webhook_url}")

    return app
