"""Telegram user client — standalone runner."""
import asyncio
import sys
sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent))

from nally.tools import load_all_tools
load_all_tools()

from nally.telegram.user import start

asyncio.run(start())
