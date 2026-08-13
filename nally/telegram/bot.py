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

# Telegram max message length
MAX_MSG_LEN = 4096
BOT_USERNAME: Optional[str] = None
BOT = None  # set in post_init, used by _make_emit for approval messages


def _web_base_url() -> str:
    """Base URL of the web server the standalone bot forwards to."""
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


def _extract_session_id(update: Update) -> str:
    """Build a session ID from the Telegram update."""
    chat = update.effective_chat
    if chat.type == "group" or chat.type == "supergroup":
        return f"telegram:group:{chat.id}"
    return f"telegram:{chat.id}"


def _clean_message_text(text: str) -> str:
    """Remove @bot mentions from message text."""
    if BOT_USERNAME:
        text = re.sub(rf"@{re.escape(BOT_USERNAME)}\s*", "", text)
    return text.strip()


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


def _make_emit_standalone(chat_id: int):
    """Emit callback for the web-server process.

    Used when the bot runs as a separate process: the web server owns the
    agent + approval gate, so the approval button is sent directly from the
    web server via its own Bot client. The full tool_call_id is used as
    callback_data (no truncation/lookup needed) since both the button and its
    resolution are handled through the web server.
    """
    loop = asyncio.get_running_loop()

    def emit(event: str, data: dict):
        if event != "confirmation_required":
            return
        from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup

        tc_id = data["tool_call_id"]
        tool = data["name"]
        args = data.get("args", {})
        args_str = " ".join(f"{k}={v}" for k, v in args.items()) if args else ""

        def _esc(s):
            return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

        text = f"<b>Permission required</b>\n\n<b>Tool:</b> <code>{_esc(tool)}</code>"
        if args_str:
            text += f"\n<b>Args:</b> <code>{_esc(args_str[:500])}</code>"

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Approve", callback_data=f"approve:{tc_id}"),
            InlineKeyboardButton("Deny", callback_data=f"deny:{tc_id}"),
        ]])

        async def _do_send():
            bot = Bot(token=os.getenv("TELEGRAM_BOT_TOKEN", ""))
            await bot.send_message(chat_id, text, parse_mode="HTML", reply_markup=keyboard)

        asyncio.run_coroutine_threadsafe(_do_send(), loop)

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
        with _callback_id_lock:
            full_tc_id = _callback_id_map.get(cb_id, cb_id)
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
                resolved = resp.json().get("resolved", False)
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

    if chat.type in ("group", "supergroup"):
        if not BOT_USERNAME or f"@{BOT_USERNAME}" not in text:
            return
        text = _clean_message_text(text)
        if not text:
            await message.reply_text("Yeah? What's up?")
            return

    session_id = _extract_session_id(update)
    try:
        await chat.send_chat_action("typing")
    except Exception:
        pass

    import httpx

    try:
        async with httpx.AsyncClient(timeout=300.0) as client:
            resp = await client.post(
                f"{_web_base_url()}/api/telegram/message",
                json={"session_id": session_id, "text": text, "chat_id": chat.id},
            )
            response = resp.json().get("response", "")
    except Exception as e:
        logger.error(f"HTTP to web server failed: {e}")
        response = f"Web server unreachable: {e}"

    if not response or response == "__EXIT__":
        return

    text_response = response.get("text", "") if isinstance(response, dict) else response
    chunks = _split_message(md_to_telegram_html(text_response))
    for chunk in chunks:
        try:
            await _send_with_retry(message.reply_text, chunk, parse_mode="HTML")
        except Exception:
            try:
                await _send_with_retry(message.reply_text, chunk)
            except Exception as e:
                logger.error(f"Telegram reply failed: {e}")


async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming voice messages (STT -> agent -> reply)."""
    message = update.message
    if not message or not message.voice:
        return

    chat = update.effective_chat
    session_id = _extract_session_id(update)

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

        # Process through agent
        emit = _make_emit(chat.id)
        if not callable(emit):
            logger.error(f"_make_emit failed to return a callable emit callback (got {emit!r})")
            emit = None
        response = await asyncio.to_thread(session_manager.process, session_id, text, emit=emit)

        if not response or response == "__EXIT__":
            return

        # Extract text from structured response
        if isinstance(response, dict):
            text_response = response.get("text", "")
        else:
            text_response = response

        # Always send voice response for voice input
        await _send_voice_response(message, text_response)

    except Exception as e:
        logger.error(f"Telegram voice error: {e}")
        try:
            await _send_with_retry(message.reply_text, f"Voice processing failed: {e}")
        except Exception:
            logger.error("Telegram voice error reply failed after retries")


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
    """Log errors from the telegram bot."""
    from telegram.error import TimedOut, NetworkError
    error = context.error
    if isinstance(error, TimedOut):
        logger.warning(f"Telegram bot timeout: {error} (likely slow agent response)")
    elif isinstance(error, NetworkError):
        logger.error(f"Telegram network error: {error}")
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
        .build()
    )

    # Store bot username and bot reference for mention detection and approval messages
    async def post_init(application: Application):
        global BOT_USERNAME, BOT
        try:
            me = await application.bot.get_me()
            BOT_USERNAME = me.username
            BOT = application.bot
            logger.info(f"Telegram bot started: @{BOT_USERNAME}")
        except Exception as e:
            # Don't take the whole bot down for a startup lookup; but be loud
            # so operators notice the degraded state (no @mention detection).
            print(f"[ERROR] Telegram bot get_me() failed at startup: {e}")
            logger.error(f"Telegram bot get_me() failed at startup: {e}")

    app.post_init = post_init

    # DEBUG: print app instance ID to verify same instance is used everywhere
    print(f"[DEBUG-APP] create_bot_app returned app id={id(app)}", flush=True)

    # Handlers
    app.add_handler(CommandHandler("start", start_command))

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
