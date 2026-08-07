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
from typing import Optional

from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from telegram import Update

from ..agent.sessions import session_manager
from ..utils.logger import logger
from .format import md_to_telegram_html

# Telegram max message length
MAX_MSG_LEN = 4096
BOT_USERNAME: Optional[str] = None
BOT = None  # set in post_init, used by _make_emit for approval messages


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

        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("Approve", callback_data=f"approve:{tc_id}"),
            InlineKeyboardButton("Deny", callback_data=f"deny:{tc_id}"),
        ]])

        try:
            if BOT:
                coro = BOT.send_message(chat_id, text, parse_mode="HTML", reply_markup=keyboard)
                asyncio.run_coroutine_threadsafe(coro, loop)
                logger.info(f"Approval message sent for tool_call_id={tc_id}")
            else:
                logger.warning("Approval emit: BOT is None, cannot send approval message")
        except Exception as e:
            logger.error(f"Approval emit failed: {e}")

    return emit


async def approval_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Approve/Deny button presses for permission gates."""
    query = update.callback_query
    if not query or not query.data:
        logger.warning(f"Approval callback: empty query or data")
        return

    logger.info(f"Approval callback received: data={query.data}")
    await query.answer()

    data = query.data
    if data.startswith("approve:") or data.startswith("deny:"):
        tc_id = data.split(":", 1)[1]
        approved = data.startswith("approve:")
        logger.info(f"Approval callback: resolving tc_id={tc_id}, approved={approved}")
        from nally.agent.graph import resolve_approval
        resolve_approval(tc_id, approved)
        try:
            await query.message.delete()
        except Exception:
            pass
    else:
        logger.warning(f"Approval callback: unexpected data format: {data}")


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "Hey! I'm Nally.\n\n"
        "Send me text or voice messages and I'll respond.\n"
        "In groups, mention me with @NallyFirstbot."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming text messages."""
    message = update.message
    if not message or not message.text:
        return

    chat = update.effective_chat
    text = message.text

    # Group chat: only respond to @mentions
    if chat.type in ("group", "supergroup"):
        if not BOT_USERNAME:
            return
        if f"@{BOT_USERNAME}" not in text:
            return
        text = _clean_message_text(text)
        if not text:
            await message.reply_text("Yeah? What's up?")
            return

    session_id = _extract_session_id(update)

    # Show typing indicator
    await chat.send_chat_action("typing")

    # Process in a thread (agent.process is blocking)
    emit = _make_emit(chat.id)
    try:
        response = await asyncio.to_thread(session_manager.process, session_id, text, emit=emit)
    except Exception as e:
        logger.error(f"Telegram agent error: {e}")
        response = f"Something went wrong: {e}"

    if not response or response == "__EXIT__":
        return

    # Extract text from structured response
    if isinstance(response, dict):
        text_response = response.get("text", "")
    else:
        text_response = response

    # Convert markdown to Telegram HTML, then send
    chunks = _split_message(md_to_telegram_html(text_response))
    for chunk in chunks:
        try:
            await message.reply_text(chunk, parse_mode="HTML")
        except Exception:
            await message.reply_text(chunk)


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

    # Show typing indicator
    await chat.send_chat_action("typing")

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
        await message.reply_text(f"Voice processing failed: {e}")


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
            await message.reply_text(md_to_telegram_html(text), parse_mode="HTML")
            return

        # Synthesize to WAV, then convert to OGG
        wav_bytes = await asyncio.to_thread(synthesize_to_wav, speak_text)
        if not wav_bytes:
            # Fallback to text
            await message.reply_text(md_to_telegram_html(text), parse_mode="HTML")
            return

        ogg_bytes = await asyncio.to_thread(wav_to_ogg, wav_bytes)
        if not ogg_bytes:
            # Fallback to text
            await message.reply_text(md_to_telegram_html(text), parse_mode="HTML")
            return

        # Send as Telegram voice message with full text as caption
        audio_file = io.BytesIO(ogg_bytes)
        audio_file.name = "nally_voice.ogg"
        caption = md_to_telegram_html(text[:1024]) if len(text) > 100 else None
        await message.reply_voice(voice=audio_file, caption=caption)

    except Exception as e:
        logger.error(f"Voice response failed: {e}")
        # Fallback to text
        await message.reply_text(md_to_telegram_html(text), parse_mode="HTML")


async def _generate_voice_summary(text: str) -> str:
    """Generate a 1-2 sentence voice summary using lightweight LLM."""
    try:
        from ..agent.llm import llm

        if len(text) <= 200:
            return text

        summary_response = await asyncio.to_thread(
            llm.chat_with_model,
            "ling-3.0-flash-free",
            [
                {"role": "system", "content": "Summarize this in 1-2 short sentences for voice. Pick the key point. Be concise and natural. Do not use markdown."},
                {"role": "user", "content": text}
            ],
            temperature=0.3,
            max_tokens=80
        )
        return summary_response.choices[0].message.content.strip()
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
    logger.error(f"Telegram bot error: {context.error}")


def create_bot_app(token: str, webhook_url: Optional[str] = None) -> Application:
    """Create and configure the Telegram bot application.

    Args:
        token: Telegram bot token
        webhook_url: If set, use webhook mode. If None, use polling.
    """
    global BOT_USERNAME

    app = Application.builder().token(token).build()

    # Store bot username and bot reference for mention detection and approval messages
    async def post_init(application: Application):
        global BOT_USERNAME, BOT
        me = await application.bot.get_me()
        BOT_USERNAME = me.username
        BOT = application.bot
        logger.info(f"Telegram bot started: @{BOT_USERNAME}")

    app.post_init = post_init

    # Handlers
    app.add_handler(CommandHandler("start", start_command))

    # Permission gate inline buttons (must be before other message handlers)
    app.add_handler(CallbackQueryHandler(approval_callback))

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
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.error("TELEGRAM_BOT_TOKEN not set in .env")
        return

    app = create_bot_app(token, webhook_url)

    if polling:
        logger.info("Starting Telegram bot in polling mode...")
        app.run_polling(drop_pending_updates=True)
    else:
        logger.info(f"Starting Telegram bot with webhook: {webhook_url}")
        app.run_webhook(
            listen="0.0.0.0",
            port=8443,
            url_path=token,
            webhook_url=f"{webhook_url}/{token}",
        )
