"""Nally Telegram bot core — text-only Bot API helpers (slim branch)."""

from __future__ import annotations

import asyncio
import logging as _logging
import os
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
from . import inline_ui
from .format import md_to_telegram_html
from .status import ProgressStatus, format_system_status

MAX_MSG_LEN = 4096
BOT_USERNAME: Optional[str] = None
BOT = None


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
        "Nally online.\n\n"
        "/status — system\n"
        "/services — MCP connect\n"
        "/connect — same as /services\n"
        "/stop — stop current run\n"
        "/abort — alias for /stop\n\n"
        "Send text to chat."
    )
    if update.effective_message:
        await update.effective_message.reply_text(msg)


async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = format_system_status(bot_username=BOT_USERNAME)
    if update.effective_message:
        await update.effective_message.reply_text(text)


async def abort_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    import httpx

    base = _web_base_url()
    chat_id = update.effective_chat.id if update.effective_chat else None
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # abort accepts verify_auth (bearer) on /api/abort
            token = os.getenv("NALLY_ACCESS_TOKEN", "") or ""
            await client.post(
                f"{base}/api/abort",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json={"session_id": f"telegram:{chat_id}"},
            )
        reply = "Abort requested."
    except Exception as e:
        reply = f"Abort failed: {e}"
    if update.effective_message:
        await update.effective_message.reply_text(reply)


async def services_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message:
        await inline_ui.show_mcp_home(update.effective_message)


async def connect_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message:
        return
    args = context.args or []
    service = (args[0] if args else "").strip().lower()
    if not service:
        await inline_ui.show_mcp_home(message)
        return
    if service not in inline_ui.MCP_SERVICES:
        await message.reply_text(
            "Unknown service. Use: github, notion, gmail, spotify, render, nalbridge"
        )
        return
    try:
        services = await inline_ui.fetch_services()
        by_name = {str(s.get("name", "")).lower(): s for s in services}
        svc = by_name.get(service, {"name": service, "status": "unknown", "connected": False})
        await message.reply_text(
            inline_ui.format_mcp_service(svc),
            parse_mode="HTML",
            reply_markup=inline_ui.keyboard_mcp_service(
                service, connected=bool(svc.get("connected"))
            ),
        )
    except Exception as e:
        await message.reply_text(f"Could not load {service}: {e}")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not message or not message.text:
        return
    chat = update.effective_chat
    session_id = f"telegram:{chat.id}" if chat else "telegram:unknown"
    route_key = session_id
    text = message.text.strip()
    if not text:
        return

    try:
        await message.chat.send_action("typing")
    except Exception:
        pass

    progress: Optional[ProgressStatus] = None
    try:
        status_msg = await message.reply_text("Thinking...", reply_markup=inline_ui.keyboard_stop())
        progress = ProgressStatus(status_msg, asyncio.get_running_loop())
    except Exception as e:
        logger.debug(f"Could not post Thinking placeholder: {e}")

    emit = progress.make_emit() if progress else (lambda _e, _d: None)

    try:
        response = await asyncio.to_thread(
            session_manager.process,
            session_id,
            text,
            emit,
            route_key,
        )
        if isinstance(response, dict):
            response = response.get("text", str(response))
        html = md_to_telegram_html(str(response or ""))

        if progress:
            ok = await progress.finish(html, parse_mode="HTML")
            if ok:
                return
        await _split_reply(message, str(response or ""))
    except Exception as e:
        logger.error(f"Telegram handle_message error: {e}")
        err = f"Error: {e}"
        if progress:
            await progress.finish(err, parse_mode=None)
        else:
            await message.reply_text(err)


async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message:
        await update.effective_message.reply_text(
            "Files/photos are limited in this build. Send text."
        )


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_message:
        await update.effective_message.reply_text(
            "Voice is not supported in this build. Send text."
        )


async def callback_query_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if not query:
        return
    handled = await inline_ui.handle_callback(query, context)
    if handled:
        return
    await query.answer()
    data = query.data or ""
    try:
        await query.edit_message_text(f"Unknown action: {data[:80]}")
    except Exception:
        pass


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Telegram error: {context.error}")
