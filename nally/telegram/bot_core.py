"""Nally Telegram bot core — text-only Bot API helpers (slim branch)."""

from __future__ import annotations

import asyncio
import logging as _logging
import os
import time
from typing import Optional

from telegram import Update
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

from ..agent.sessions import session_manager
from ..utils.logger import logger
from .format import md_to_telegram_html

MAX_MSG_LEN = 4096
BOT_USERNAME: Optional[str] = None
BOT = None
_start_time = time.time()


class _GetAddrInfoFilter(_logging.Filter):
    _last_log = 0.0

    def filter(self, record: _logging.LogRecord) -> bool:
        msg = record.getMessage() + " " + str(getattr(record, "exc_info", "") or "")
        if "getaddrinfo failed" in msg or "11001" in msg or "WinError 1231" in msg:
            import time as _time

            now = _time.monotonic()
            if now - self._last_log < 30:
                return False
            self._last_log = now
            record.levelno = _logging.WARNING
            record.levelname = "WARNING"
            record.exc_info = None
            record.exc_text = None
            record.msg = (
                "Telegram polling DNS/network down — check internet/DNS for api.telegram.org. Retrying…"
            )
            record.args = ()
            return True
        return True


for _lname in (
    "telegram.ext.Updater",
    "telegram.request.BaseRequest",
    "telegram.request.HTTPXRequest",
    "httpx",
    "httpcore",
):
    try:
        _logging.getLogger(_lname).addFilter(_GetAddrInfoFilter())
        _logging.getLogger(_lname).setLevel(_logging.WARNING)
    except Exception:
        pass


def _web_base_url() -> str:
    from ..config import NALLY_BASE_URL

    if NALLY_BASE_URL:
        return NALLY_BASE_URL.rstrip("/")
    port = os.getenv("PORT") or os.getenv("NALLY_PORT") or "5000"
    return f"http://localhost:{port}"


def _internal_headers() -> dict:
    token = os.getenv("NALLY_INTERNAL_TOKEN") or os.getenv("NALLY_ACCESS_TOKEN") or ""
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


async def _split_reply(message, text: str):
    text = (text or "").strip() or "(empty response)"
    html = md_to_telegram_html(text)
    chunks = []
    while html:
        if len(html) <= MAX_MSG_LEN:
            chunks.append(html)
            break
        cut = html.rfind("\n", 0, MAX_MSG_LEN)
        if cut < MAX_MSG_LEN // 2:
            cut = MAX_MSG_LEN
        chunks.append(html[:cut])
        html = html[cut:].lstrip("\n")
    for chunk in chunks:
        try:
            await message.reply_text(chunk, parse_mode="HTML", disable_web_page_preview=True)
        except Exception:
            await message.reply_text(chunk[:MAX_MSG_LEN])


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = (
        "Nally is online (Telegram-only slim build).\n\n"
        "Commands:\n"
        "/start — this message\n"
        "/status — provider, model, uptime, tools\n"
        "/abort — cancel the current run\n"
        "/services — MCP service readiness\n"
        "/connect <service> — github | notion | gmail | spotify | render | nalbridge\n\n"
        "Send text messages to chat. Voice is not supported in this build."
    )
    if update.effective_message:
        await update.effective_message.reply_text(msg)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import httpx

    base = _web_base_url()
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            r = await client.get(f"{base}/health", headers=_internal_headers())
            body = r.text[:1500]
    except Exception as e:
        body = f"Backend unreachable: {e}"
    uptime = int(time.time() - _start_time)
    text = f"Uptime: {uptime}s\nBot: @{BOT_USERNAME or '?'}\n\n{body}"
    if update.effective_message:
        await update.effective_message.reply_text(text[:MAX_MSG_LEN])


async def abort_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import httpx

    base = _web_base_url()
    chat_id = update.effective_chat.id if update.effective_chat else None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            await client.post(
                f"{base}/api/abort",
                headers=_internal_headers(),
                json={"session_id": f"telegram:{chat_id}"},
            )
        reply = "Abort requested."
    except Exception as e:
        reply = f"Abort failed: {e}"
    if update.effective_message:
        await update.effective_message.reply_text(reply)


async def services_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import httpx

    base = _web_base_url()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            r = await client.get(f"{base}/api/mcp/services", headers=_internal_headers())
            body = r.text[:3000]
    except Exception as e:
        body = f"Could not load services: {e}"
    if update.effective_message:
        await update.effective_message.reply_text(body[:MAX_MSG_LEN])


async def connect_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import httpx

    args = (context.args or [])
    service = (args[0] if args else "").strip().lower()
    if not service:
        if update.effective_message:
            await update.effective_message.reply_text(
                "Usage: /connect github|notion|gmail|spotify|render|nalbridge"
            )
        return
    base = _web_base_url()
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.post(
                f"{base}/api/mcp/connect",
                headers=_internal_headers(),
                json={"service": service},
            )
            body = r.text[:2000]
    except Exception as e:
        body = f"Connect failed: {e}"
    if update.effective_message:
        await update.effective_message.reply_text(body[:MAX_MSG_LEN])


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.text:
        return
    chat = update.effective_chat
    user = update.effective_user
    session_id = f"telegram:{chat.id}" if chat else "telegram:unknown"
    text = message.text.strip()
    if not text:
        return

    await message.chat.send_action("typing")

    def emit(event: str, data: dict):
        # Approvals are handled via backend -> bot callbacks when configured.
        return None

    try:
        agent = session_manager.get_or_create(
            session_id,
            channel="Telegram",
            route_key=session_id,
        )
        response = await asyncio.to_thread(agent.process, text, emit)
        await _split_reply(message, response)
    except Exception as e:
        logger.error(f"Telegram handle_message error: {e}")
        await message.reply_text(f"Error: {e}")


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message:
        await update.effective_message.reply_text(
            "File/photo handling is limited in this slim build. Please send text, or describe the file."
        )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message:
        await update.effective_message.reply_text(
            "Voice messages are not supported in this build. Please send text."
        )


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    await query.answer()
    data = query.data or ""
    # Approval buttons: approve:<id> / deny:<id>
    import httpx

    base = _web_base_url()
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            await client.post(
                f"{base}/api/telegram/callback",
                headers=_internal_headers(),
                json={"data": data, "user_id": query.from_user.id if query.from_user else None},
            )
        await query.edit_message_text(f"Recorded: {data[:200]}")
    except Exception as e:
        await query.edit_message_text(f"Callback failed: {e}")


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Telegram error: {context.error}")
