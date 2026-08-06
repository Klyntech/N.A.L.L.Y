"""Nally Telegram Bot — DM + group chat via python-telegram-bot.

Supports:
- Text messages: process through agent, reply as text
- Voice messages: STT -> agent -> text reply
- /voice command: toggle voice responses (TTS -> OGG/Opus)
- /text command: switch back to text-only mode

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
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from telegram import Update

from ..agent.sessions import session_manager
from ..utils.logger import logger

# Telegram max message length
MAX_MSG_LEN = 4096
BOT_USERNAME: Optional[str] = None

# Per-user voice preferences: {chat_id: bool}
_voice_enabled: dict[int, bool] = {}


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


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        "Hey! I'm Nally.\n\n"
        "Send me text or voice messages and I'll respond.\n"
        "In groups, mention me with @NallyFirstbot.\n\n"
        "Commands:\n"
        "/voice - Toggle voice responses\n"
        "/text - Switch to text-only mode"
    )


async def voice_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Toggle voice responses for this user."""
    chat_id = update.effective_chat.id
    _voice_enabled[chat_id] = not _voice_enabled.get(chat_id, False)

    if _voice_enabled[chat_id]:
        await update.message.reply_text("Voice responses ON. I'll reply with audio.")
    else:
        await update.message.reply_text("Voice responses OFF. Text only.")


async def text_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Switch to text-only mode."""
    chat_id = update.effective_chat.id
    _voice_enabled[chat_id] = False
    await update.message.reply_text("Switched to text mode.")


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
    try:
        response = await asyncio.to_thread(session_manager.process, session_id, text)
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

    # Voice response if enabled
    chat_id = chat.id
    if _voice_enabled.get(chat_id, False):
        await _send_voice_response(message, text_response)
    else:
        # Split and send as text (Telegram has a 4096 char limit)
        chunks = _split_message(text_response)
        for chunk in chunks:
            try:
                await message.reply_text(chunk, parse_mode="Markdown")
            except Exception:
                # Fallback: send without markdown if parsing fails
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
        response = await asyncio.to_thread(session_manager.process, session_id, text)

        if not response or response == "__EXIT__":
            return

        # Extract text from structured response
        if isinstance(response, dict):
            text_response = response.get("text", "")
        else:
            text_response = response

        # Send voice response if enabled, else text
        chat_id = chat.id
        if _voice_enabled.get(chat_id, False):
            await _send_voice_response(message, text_response)
        else:
            # Send transcript + text response
            chunks = _split_message(f"**You said:** {text}\n\n{text_response}")
            for chunk in chunks:
                try:
                    await message.reply_text(chunk, parse_mode="Markdown")
                except Exception:
                    await message.reply_text(chunk)

    except Exception as e:
        logger.error(f"Telegram voice error: {e}")
        await message.reply_text(f"Voice processing failed: {e}")


async def _send_voice_response(message, text: str):
    """Send a voice response (TTS -> OGG -> Telegram voice message)."""
    try:
        from ..voice.formatter import VoiceFormatter, VoiceMode
        from ..voice.tts import synthesize_to_wav
        from .voice import wav_to_ogg

        # Format for speech (strip code, tables, etc.)
        formatter = VoiceFormatter()
        speak_text = formatter.format(text, mode=VoiceMode.SMART)

        if not speak_text:
            await message.reply_text(text)
            return

        # Synthesize to WAV, then convert to OGG
        wav_bytes = await asyncio.to_thread(synthesize_to_wav, speak_text)
        if not wav_bytes:
            # Fallback to text
            await message.reply_text(text)
            return

        ogg_bytes = await asyncio.to_thread(wav_to_ogg, wav_bytes)
        if not ogg_bytes:
            # Fallback to text
            await message.reply_text(text)
            return

        # Send as Telegram voice message
        audio_file = io.BytesIO(ogg_bytes)
        audio_file.name = "nally_voice.ogg"
        await message.reply_voice(voice=audio_file, caption=text[:1024] if len(text) > 100 else None)

    except Exception as e:
        logger.error(f"Voice response failed: {e}")
        # Fallback to text
        await message.reply_text(text)


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

    # Store bot username for mention detection
    async def post_init(application: Application):
        global BOT_USERNAME
        me = await application.bot.get_me()
        BOT_USERNAME = me.username
        logger.info(f"Telegram bot started: @{BOT_USERNAME}")

    app.post_init = post_init

    # Handlers
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("voice", voice_command))
    app.add_handler(CommandHandler("text", text_command))

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
