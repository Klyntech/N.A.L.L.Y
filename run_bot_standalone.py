"""Run Nally Telegram bot as a separate process.

The bot polls Telegram in its own process with its own main-thread event loop.
It forwards incoming messages and approval clicks to the web server (main.py,
port 5000) over HTTP. This avoids both the PTB v21 daemon-thread event-loop
issues and the cross-process thread-pool deadlock in the approval gate.

Single-owner enforcement (Path B): this standalone poller is ONLY for polling
mode. If the resolved Telegram mode is webhook or off, the bot exits cleanly
so it never competes with the web server's own Application on the same token.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

load_dotenv()

from nally.config import resolve_telegram_mode
from nally.telegram.bot import run_telegram_bot

if __name__ == "__main__":
    if resolve_telegram_mode() != "polling":
        print(
            "Telegram mode is not 'polling' — the standalone poller is not the owner. "
            "Exiting without starting the bot."
        )
        sys.exit(0)
    run_telegram_bot(polling=True)