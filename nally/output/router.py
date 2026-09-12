"""Output Router — chooses text vs voice representation (V2).

V2 diagram:
  RESPONSE COMPOSER → OUTPUT ROUTER → TEXT (SSE/WS/Telegram) | VOICE (SpeechPlanner→TTS→Audio)

Single branch point for all channels. Voice remains Telegram-primary; Web
voice is gated behind an explicit flag so the router is forward-compatible
without exposing an unfinished surface.

Web handlers, Telegram bot, and CLI all call this module instead of
hand-rolling their own md→HTML / voice-pacing branches.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nally.output.router")

class OutputTarget(StrEnum):
    TEXT = "text"
    VOICE = "voice"
    BOTH = "both"  # text + voice attachment (Telegram voice reply)

@dataclass
class RoutedOutput:
    target: OutputTarget
    text: str  # plain text (already composed) — for TEXT or caption
    html: Optional[str] = None  # Telegram HTML (when target includes TEXT)
    voice_text: Optional[str] = None  # text used for TTS (may be shortened)
    voice_format: str = ""  # "", "wav", "ogg"
    attachments: List[str] = field(default_factory=list)
    chunks: List[str] = field(default_factory=list)  # split segments for Telegram

class OutputRouter:
    """Branch TEXT vs VOICE. No I/O; callers perform the actual send."""

    def route(
        self,
        text: str,
        *,
        channel: str = "",
        wants_voice: bool = False,
        voice_profile: str = "nally",
    ) -> RoutedOutput:
        """Decide representation for this turn.

        Args:
            text: Composed final text from ResponseComposer.
            channel: Origin channel label (e.g. "telegram:123", "web:default").
            wants_voice: True when the user sent a voice message or requested voice.
            voice_profile: nally|narrator|concise|warm

        Returns:
            RoutedOutput describing what the caller should send and how.

        Invariants:
          - Voice is only routed for Telegram-family channels unless
            NALLY_WEB_VOICE_ENABLED is set. Web callers that pass
            wants_voice=True still get TEXT with a gentle hint when disabled.
          - Telegram voice never drops the text — Both target keeps transcript.
        """
        ch = (channel or "").lower()
        is_telegram = ch.startswith("telegram") or "telegram" in ch
        is_web = ch.startswith("web") or ch.startswith("ws") or "web:" in ch

        # Web voice gate
        web_voice_enabled = False
        try:
            import os as _os
            web_voice_enabled = _os.getenv("NALLY_WEB_VOICE_ENABLED", "false").lower() in ("true", "1", "yes")
        except Exception:
            pass

        if wants_voice and is_web and not web_voice_enabled:
            # Keep TEXT but annotate for callers that want to show a hint
            logger.debug("OutputRouter: web voice requested but NALLY_WEB_VOICE_ENABLED=false → TEXT")
            # Do not mutate text here; caller (ws_handler) decides the hint/error shape
            target = OutputTarget.TEXT
            html = self._to_telegram_html(text) if is_telegram else None
            return RoutedOutput(target=target, text=text, html=html, voice_text=None)

        if wants_voice and (is_telegram or (is_web and web_voice_enabled)):
            # Telegram-family: text + voice; Web+enabled: voice
            html = self._to_telegram_html(text) if is_telegram else None
            # Voice text may be shortened by formatter downstream; keep full for now
            vt = self._voice_summarize(text) if len(text) > 800 else text
            target = OutputTarget.BOTH if is_telegram else OutputTarget.VOICE
            fmt = "ogg" if is_telegram else "wav"
            return RoutedOutput(target=target, text=text, html=html, voice_text=vt, voice_format=fmt)

        # Default: text
        html = self._to_telegram_html(text) if is_telegram else None
        chunks = self._split_telegram(html) if is_telegram and html else []
        return RoutedOutput(target=OutputTarget.TEXT, text=text, html=html, voice_text=None, chunks=chunks)

    def _to_telegram_html(self, text: str) -> Optional[str]:
        try:
            from ..telegram.format import md_to_telegram_html
            return md_to_telegram_html(text)
        except Exception:
            return None

    def _split_telegram(self, html: str, limit: int = 4096) -> List[str]:
        """Split Telegram HTML at paragraph/newline boundaries.

        Telegram's per-message limit is 4096 characters. This method
        preserves the same splitting logic as bot.py._split_message()
        but is owned by the OutputRouter so all surfaces share it.
        """
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

    def _voice_summarize(self, text: str) -> str:
        try:
            from ..voice.formatter import VoiceFormatter
            fmt = VoiceFormatter()
            # SMART: full <200 else summary; keeps voice natural
            return fmt.format_for_voice(text, mode="smart")
        except Exception:
            # Fallback: strip markdown-ish, clamp
            import re as _re
            t = _re.sub(r"[#*_`>\[\]]", "", text)
            return t[:600]

# Singleton
_output_router: Optional[OutputRouter] = None

def get_output_router() -> OutputRouter:
    global _output_router
    if _output_router is None:
        _output_router = OutputRouter()
    return _output_router

def route_output(text: str, **kwargs) -> RoutedOutput:
    return get_output_router().route(text, **kwargs)
