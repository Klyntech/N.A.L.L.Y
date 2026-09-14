"""Output Router — text representation for all channels.

All responses are text-only. The router handles Telegram HTML conversion
and message splitting. No voice/audio path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import List, Optional

logger = logging.getLogger("nally.output.router")

class OutputTarget(StrEnum):
    TEXT = "text"

@dataclass
class RoutedOutput:
    target: OutputTarget
    text: str
    html: Optional[str] = None
    chunks: List[str] = field(default_factory=list)

class OutputRouter:
    """Branch TEXT only. No I/O; callers perform the actual send."""

    def route(
        self,
        text: str,
        *,
        channel: str = "",
    ) -> RoutedOutput:
        ch = (channel or "").lower()
        is_telegram = ch.startswith("telegram") or "telegram" in ch

        html = self._to_telegram_html(text) if is_telegram else None
        chunks = self._split_telegram(html) if is_telegram and html else []
        return RoutedOutput(target=OutputTarget.TEXT, text=text, html=html, chunks=chunks)

    def _to_telegram_html(self, text: str) -> Optional[str]:
        try:
            from ..telegram.format import md_to_telegram_html
            return md_to_telegram_html(text)
        except Exception:
            return None

    def _split_telegram(self, html: str, limit: int = 4096) -> List[str]:
        if not html or len(html) <= limit:
            return [html] if html else []
        chunks: List[str] = []
        remaining = html
        while remaining:
            if len(remaining) <= limit:
                chunks.append(remaining)
                break
            split_at = remaining.rfind("\n\n", 0, limit)
            if split_at < limit // 2:
                split_at = remaining.rfind("\n", 0, limit)
            if split_at < limit // 2:
                split_at = limit
            chunks.append(remaining[:split_at])
            remaining = remaining[split_at:].lstrip("\n")
        return chunks

# Singleton
_output_router: Optional[OutputRouter] = None

def get_output_router() -> OutputRouter:
    global _output_router
    if _output_router is None:
        _output_router = OutputRouter()
    return _output_router

def route_output(text: str, **kwargs) -> RoutedOutput:
    return get_output_router().route(text, **kwargs)
