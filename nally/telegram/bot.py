"""Nally Telegram Bot — Bot API only (slim branch)."""
from typing import Optional

from .bot_core import *  # noqa: F403

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

    app = Application.builder().token(token).request(request).concurrent_updates(True).build()

    async def post_init(application: Application):
        global BOT_USERNAME, BOT
        try:
            import socket as _socket

            _socket.getaddrinfo("api.telegram.org", 443, timeout=3)
        except Exception as _dns_e:
            logger.warning(
                f"DNS check failed for api.telegram.org at startup: {_dns_e} — check internet/DNS/proxy. Will retry get_me…"
            )

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
                msg = f"Telegram bot get_me() failed at startup (attempt {_attempt + 1}/3): {e}"
                if is_dns:
                    msg += " — DNS/network down, will retry polling anyway"
                print(f"[{'WARN' if is_dns else 'ERROR'}] {msg}")
                level(msg)
                if _attempt < 2:
                    await asyncio.sleep(2 ** (_attempt + 1))
                else:
                    print("[WARN] Telegram bot get_me() failed after 3 attempts — bot will still try to poll")

    app.post_init = post_init

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("status", status_command))
    app.add_handler(CommandHandler("abort", abort_command))
    app.add_handler(CommandHandler("services", services_command))
    app.add_handler(CommandHandler("connect", connect_command))
    app.add_handler(CallbackQueryHandler(callback_query_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(MessageHandler(filters.PHOTO | filters.Document.ALL, handle_document))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, handle_voice))
    app.add_error_handler(error_handler)

    return app


def run_telegram_bot(polling: bool = True, webhook_url: Optional[str] = None):
    """Start the Telegram bot.

    Args:
        polling: Use polling mode (default, good for dev)
        webhook_url: If set, use webhook mode instead of polling
    """
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("[FATAL] TELEGRAM_BOT_TOKEN not set")
        logger.error("TELEGRAM_BOT_TOKEN not set")
        return

    app = create_bot_app(token, webhook_url)

    async def _run_bot():
        try:
            await app.initialize()
            await app.start()
            if polling:
                await app.updater.start_polling(
                    allowed_updates=[
                        UpdateType.MESSAGE,
                        UpdateType.CALLBACK_QUERY,
                    ],
                    drop_pending_updates=True,
                )
                logger.info("Telegram bot polling started")
                # Block until cancelled
                stop_event = asyncio.Event()
                try:
                    await stop_event.wait()
                except asyncio.CancelledError:
                    pass
            else:
                logger.info("Telegram bot app started (webhook mode — external registration required)")
                stop_event = asyncio.Event()
                try:
                    await stop_event.wait()
                except asyncio.CancelledError:
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
    """Telegram bot runs as a separate process (run_bot_standalone.py)."""
    logger.info("Telegram bot runs as a separate process — skipping inline start")
    return None


async def stop_telegram_polling(app: Optional[Application]):
    """Gracefully stop a polling Application."""
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
    """Start Telegram bot in webhook mode and register with Telegram API."""
    global BOT, BOT_USERNAME

    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not set — Telegram webhook not started")
        return None

    app = create_bot_app(token, webhook_base_url)

    await app.initialize()
    await app.start()

    webhook_path = f"/telegram/webhook/{token}"
    full_webhook_url = f"{webhook_base_url.rstrip('/')}{webhook_path}"

    await app.bot.set_webhook(
        url=full_webhook_url,
        allowed_updates=[
            "message",
            "callback_query",
        ],
    )
    logger.info("Telegram webhook registered successfully")

    return app
