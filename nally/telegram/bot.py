"""Nally Telegram Bot — DM + group chat via python-telegram-bot.

Usage:
    python main.py --telegram          # Run web server + Telegram bot
    python main.py --telegram-only     # Telegram bot only

Requires TELEGRAM_BOT_TOKEN in .env.
"""

import asyncio
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
        "Hey! I'm Nally. Send me a message and I'll respond.\nIn groups, mention me with @NallyFirstbot."
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
    try:
        response = await asyncio.to_thread(session_manager.process, session_id, text)
    except Exception as e:
        logger.error(f"Telegram agent error: {e}")
        response = f"Something went wrong: {e}"

    if not response or response == "__EXIT__":
        return

    # Split and send (Telegram has a 4096 char limit)
    chunks = _split_message(response)
    for chunk in chunks:
        try:
            await message.reply_text(chunk, parse_mode="Markdown")
        except Exception:
            # Fallback: send without markdown if parsing fails
            await message.reply_text(chunk)


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
        nonlocal BOT_USERNAME
        me = await application.bot.get_me()
        BOT_USERNAME = me.username
        logger.info(f"Telegram bot started: @{BOT_USERNAME}")

    app.post_init = post_init

    # Handlers
    app.add_handler(CommandHandler("start", start_command))
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
