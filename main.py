#!/usr/bin/env python3
"""
Nally - Your Personal AI Assistant
Inspired by Jarvis from Iron Man
"""

import argparse
import os
import sys
import time
from pathlib import Path

from rich.console import Console

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))


def main():
    parser = argparse.ArgumentParser(description="Nally - Your AI Assistant")
    parser.add_argument("--cli", action="store_true", help="Run in CLI mode")
    parser.add_argument("--voice", action="store_true", help="Run in voice mode (push-to-talk)")
    parser.add_argument("--telegram-only", action="store_true", help="Run Telegram bot only")
    parser.add_argument("--port", type=int, default=5000, help="Web server port (default: 5000)")
    parser.add_argument("--provider", choices=["groq", "opencode"], help="Override LLM provider")
    parser.add_argument("--verbose", action="store_true", help="Show full MCP server tree during startup")
    parser.add_argument(
        "--engineer",
        metavar="TASK",
        help="Run the autonomous engineering loop on TASK (opt-in build mode).",
    )
    args = parser.parse_args()

    if args.port < 1024 or args.port > 65535:
        print(f"Error: port must be between 1024 and 65535, got {args.port}")
        sys.exit(1)

    # Override provider if specified
    if args.provider:
        import os

        os.environ["NALLY_PROVIDER"] = args.provider

    from nally import __version__
    from nally.core.startup import StartupDisplay, print_banner

    console = Console()
    display = StartupDisplay(console)

    print_banner(version=__version__, console=console)

    # Load tools for non-web modes (web mode loads via app.py lifespan)
    if args.cli or args.telegram_only:
        from nally.tools import load_all_tools

        _tool_count, mcp_status = load_all_tools()

        display.phase("Tools", f"[green]{_tool_count} registered[/]")
        if mcp_status:
            display.mcp_summary(mcp_status, verbose=args.verbose)

    # Opt-in autonomous engineering mode (does not affect normal chat startup).
    if args.engineer:
        from nally.engineering import run_engineering

        result = run_engineering(args.engineer, verbose=True)
        print(f"\nEngineering build: {result.task}")
        print(f"Status: {'SUCCESS' if result.success else 'COMPLETED WITH ISSUES'}")
        if result.chosen_approach:
            print(f"Approach: {result.chosen_approach.title}")
        print(f"Output dir: {result.readme_path}")
        for cmd in result.run_commands:
            print(f"  {cmd}")
        return

    if args.cli:
        run_cli()
    elif args.voice:
        run_voice()
    elif args.telegram_only:
        run_telegram(polling=True)
    else:
        # Default mode runs the web server. The Telegram bot owner is decided
        # by resolve_telegram_mode(): polling mode spawns a separate bot
        # process, webhook mode is owned by the web server's lifespan. Exactly
        # one owner per token.
        run_web(port=args.port)


def run_cli():
    """Run Nally in CLI mode"""
    from nally.agent import get_agent

    agent = get_agent()

    print("Nally CLI Mode")
    print("-" * 40)
    print("Commands: 'quit' to exit")
    print()

    while True:
        try:
            user_input = input("You]: ").strip()

            if user_input.lower() in ["quit", "exit", "bye"]:
                print("\nNally: Goodbye!")
                break

            if not user_input:
                continue

            print("\nNally: ", end="", flush=True)

            start = time.time()
            response = agent.process(user_input)
            elapsed = time.time() - start

            print(response)

            if elapsed < 1:
                print(f"  [{elapsed * 1000:.0f}ms]", end="")
            print()

        except KeyboardInterrupt:
            print("\n\nNally: Interrupted. Goodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")


def run_voice():
    """Run Nally in voice mode (push-to-talk)."""
    from nally.voice.loop import run_voice_loop

    run_voice_loop()


def run_web(port=5000):
    """Run Nally in web mode (Jarvis React UI)"""
    import atexit
    import logging
    import os
    import subprocess
    import sys
    import threading
    import time
    import webbrowser

    os.environ["PORT"] = str(port)
    os.environ["NALLY_PORT"] = str(port)

    # Suppress Uvicorn's noisy startup/access logs
    class _UvicornFilter(logging.Filter):
        def filter(self, record):
            return False

    for name in ("uvicorn", "uvicorn.access", "uvicorn.error"):
        logging.getLogger(name).addFilter(_UvicornFilter())

    # Auto-open browser
    def _open():
        time.sleep(2)
        webbrowser.open(f"http://localhost:{port}")

    threading.Thread(target=_open, daemon=True).start()

    # The Telegram bot runs as a SEPARATE process (its own event loop) and
    # forwards messages/approvals to this web server over HTTP. Spawn it here
    # so `python main.py` stays a single command. (Use --telegram-only to run
    # the bot without the web server.)
    #
    # Single-owner enforcement: the standalone poller is spawned ONLY when the
    # resolved mode is polling. In webhook mode the web server owns Telegram
    # via its own Application (started in the FastAPI lifespan), so spawning a
    # second poller here would cause a Telegram 409 conflict on the same token.
    bot_proc = None
    from nally.config import resolve_telegram_mode, TELEGRAM_USER_ID

    telegram_mode = resolve_telegram_mode()
    if telegram_mode == "polling":
        bot_proc = subprocess.Popen(
            [sys.executable, "run_bot_standalone.py"],
            cwd=str(Path(__file__).parent),
        )
        print("Telegram bot launched as a separate process (run_bot_standalone.py).")
    elif telegram_mode == "webhook":
        print("Telegram bot owned by web server (webhook mode) — no separate poller spawned.")
    else:
        print("[warn] TELEGRAM_BOT_TOKEN not set or TELEGRAM_MODE=off — Telegram bot not started "
              "(web server is still running).")

    def _kill_bot():
        if bot_proc is not None and bot_proc.poll() is None:
            bot_proc.terminate()
            try:
                bot_proc.wait(timeout=5)
            except Exception:
                bot_proc.kill()

    def _kill_tg_user():
        if tg_user_proc is not None and tg_user_proc.poll() is None:
            tg_user_proc.terminate()
            try:
                tg_user_proc.wait(timeout=5)
            except Exception:
                tg_user_proc.kill()

    atexit.register(_kill_bot)
    atexit.register(_kill_tg_user)

    # Start Telegram user account (Telethon) as a separate process
    # Voice calls are handled inside user.py (same process, same Telethon client)
    tg_user_proc = None
    from nally.config import resolve_telegram_mode, TELEGRAM_USER_ID, DATA_DIR

    _tg_session = DATA_DIR / "telegram_user" / "nally_user.session"

    if TELEGRAM_USER_ID and os.getenv("NALLY_TELEGRAM_USER_ENABLED", "1") == "0":
        print("[skip] NALLY_TELEGRAM_USER_ENABLED=0 — Telegram user account disabled.")
    elif TELEGRAM_USER_ID and not _tg_session.exists():
        print(f"[skip] No Telethon session file at {_tg_session} — run locally first to authenticate.")
    elif TELEGRAM_USER_ID:
        tg_user_proc = subprocess.Popen(
            [sys.executable, "run_tg_user.py"],
            cwd=str(Path(__file__).parent),
        )
        print("Telegram user account launched as a separate process (run_tg_user.py).")
    else:
        print("[warn] TELEGRAM_USER_ID not set — Telegram user account not started.")

    import signal
    import uvicorn

    from nally.web.app import app

    # Graceful shutdown: Render sends SIGTERM on deploy. Give in-flight
    # requests time to complete before uvicorn starts its shutdown sequence.
    def _handle_sigterm(sig, frame):
        print("[shutdown] SIGTERM received — draining in-flight requests...")

    signal.signal(signal.SIGTERM, _handle_sigterm)

    try:
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=port,
            log_level="warning",
            timeout_graceful_shutdown=30,
        )
    finally:
        _kill_bot()
        _kill_tg_user()


def run_telegram(polling=True, webhook_url=None):
    """Run Nally Telegram bot."""
    from nally.telegram.bot import run_telegram_bot

    print("Starting Nally Telegram bot...")
    print("Press Ctrl+C to stop")
    print()
    run_telegram_bot(polling=polling, webhook_url=webhook_url)


if __name__ == "__main__":
    main()
