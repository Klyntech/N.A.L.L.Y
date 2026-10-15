"""Telegram status helpers — /status text and Thinking... / Using {tool}... progress."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Callable, Optional

from ..utils.logger import logger

_START_TIME = time.time()


def get_start_time() -> float:
    return _START_TIME


def format_uptime(start: Optional[float] = None) -> str:
    uptime = time.time() - (start if start is not None else _START_TIME)
    days = int(uptime // 86400)
    hours = int((uptime % 86400) // 3600)
    minutes = int((uptime % 3600) // 60)
    if days:
        return f"{days}d {hours}h {minutes}m"
    return f"{hours}h {minutes}m"


def format_system_status(*, bot_username: Optional[str] = None) -> str:
    """Build the /status reply body (provider, model, tools, budget, uptime)."""
    try:
        from ..config import ACTIVE_MODEL, PROVIDER

        provider = PROVIDER
        model = ACTIVE_MODEL
    except Exception:
        provider, model = "unknown", "unknown"

    try:
        from ..agent.context import context_manager

        stats = context_manager.get_stats()
        daily_used = stats.get("daily_tokens", 0)
        budget = stats.get("daily_token_budget", 0)
        if budget > 0:
            budget_line = f"Token budget: {daily_used:,}/{budget:,} used"
        else:
            budget_line = "Token budget: unlimited"
    except Exception:
        budget_line = "Token budget: unavailable"

    try:
        from ..tools.registry import registry

        tool_count = len(registry.tools)
    except Exception:
        tool_count = 0

    try:
        from ..config import DATA_DIR

        db_path = DATA_DIR / "nally_memory.db"
        db_size = f"{db_path.stat().st_size / 1024:.0f}KB" if db_path.exists() else "new"
    except Exception:
        db_size = "unknown"

    lines = [
        "Nally Status",
        "─────────────",
        f"Provider: {provider}",
        f"Model: {model}",
        f"Uptime: {format_uptime()}",
        f"Tools: {tool_count} loaded",
        f"DB: {db_size}",
        budget_line,
    ]
    if bot_username:
        lines.insert(2, f"Bot: @{bot_username}")
    return "\n".join(lines)


class ProgressStatus:
    """Placeholder message: Thinking... then Using {tool}... then the final reply.

    Thoughts, system notices, and tool results stay internal — not shown to the user.
    """

    def __init__(self, status_message: Any, loop: asyncio.AbstractEventLoop):
        self._msg = status_message
        self._loop = loop
        self._last = ""

    def set(self, text: str) -> None:
        """Thread-safe status line update (from emit in a worker thread)."""
        if not text or text == self._last:
            return
        self._last = text
        try:
            asyncio.run_coroutine_threadsafe(self._edit(text), self._loop)
        except Exception as e:
            logger.debug(f"ProgressStatus.set failed: {e}")

    async def _edit(self, text: str) -> None:
        if not self._msg:
            return
        try:
            await self._msg.edit_text(text[:4000])
        except Exception as e:
            err = str(e).lower()
            if "not modified" in err or "message is not modified" in err:
                return
            logger.debug(f"ProgressStatus edit failed: {e}")

    async def finish(self, final_text: str, *, parse_mode: Optional[str] = "HTML") -> bool:
        """Replace the status placeholder with the final reply."""
        if not self._msg:
            return False
        body = (final_text or "").strip() or "(empty response)"
        try:
            await self._msg.edit_text(body[:4000], parse_mode=parse_mode)
            return True
        except Exception:
            try:
                await self._msg.edit_text(body[:4000])
                return True
            except Exception as e:
                logger.debug(f"ProgressStatus.finish failed: {e}")
                return False

    def make_emit(self, extra: Optional[Callable[[str, dict], None]] = None) -> Callable[[str, dict], None]:
        """Emit: only surface active tool name; everything else stays internal."""

        def emit(event: str, data: dict) -> None:
            try:
                if event == "tool_call":
                    name = ((data or {}).get("name") or "?").strip() or "?"
                    self.set(f"Using {name}...")
                # thought / tool_result / system_notice / etc. — internal only
            except Exception as e:
                logger.debug(f"ProgressStatus emit error: {e}")
            if extra:
                try:
                    extra(event, data)
                except Exception:
                    pass

        return emit
