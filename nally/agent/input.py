"""Nally Input Normalizer — single typed entry for all channels (V2).

Converts Telegram/Web/voice/etc. into one typed Input so the Controller,
Context Builder, and Output Router share the same identity contract:

    Input{text, audio?, image?, route_key, channel, session_id, wants_voice}

Channels keep their own transport (bot.py STT, media.py image desc, web SSE)
but must normalize before calling SessionManager.process(). String passthrough
remains for backward compat (CLI, tests, queued messages).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class Input:
    """Typed turn input. `text` is already transcribed/described (STT/image done upstream)."""

    text: str
    channel: str = ""  # e.g. "telegram:123", "web:default", "cli", "tg_voice:456"
    route_key: str = ""
    session_id: str = "default"
    wants_voice: bool = False
    audio: Optional[bytes] = None  # raw audio when caller defers STT (rare)
    image: Optional[str] = None  # image description/path when multimodal
    meta: Dict[str, Any] = field(default_factory=dict)

    def effective_route(self) -> str:
        return self.route_key or self.session_id

    def is_telegram(self) -> bool:
        ch = (self.channel or "").lower()
        return "telegram" in ch or "tg_voice" in ch

    def is_web(self) -> bool:
        ch = (self.channel or "").lower()
        return ch.startswith("web") or ch.startswith("ws") or "web:" in ch


def normalize_input(
    raw: Any,
    *,
    channel: str = "",
    route_key: str = "",
    session_id: str = "default",
    wants_voice: bool = False,
) -> Input:
    """Normalize str | dict | Input into an Input.

    - Input → returned as-is (fills missing session/route defaults).
    - dict with 'text' → mapped (supports web/telegram POST shapes).
    - str → wrapped with provided channel/route/session context.
    """
    if isinstance(raw, Input):
        if not raw.session_id:
            raw.session_id = session_id
        if not raw.route_key:
            raw.route_key = route_key or raw.session_id
        if not raw.channel and channel:
            raw.channel = channel
        return raw
    if isinstance(raw, dict):
        text = str(raw.get("text", raw.get("message", raw.get("caption", ""))) or "")
        return Input(
            text=text,
            channel=str(raw.get("channel", channel) or ""),
            route_key=str(raw.get("route_key", route_key) or session_id),
            session_id=str(raw.get("session_id", session_id) or "default"),
            wants_voice=bool(raw.get("wants_voice", wants_voice)),
            image=raw.get("image") or raw.get("media_desc"),
            meta={k: v for k, v in raw.items() if k not in ("text", "message", "caption")},
        )
    # Plain string (CLI, tests, queue drain)
    return Input(
        text=str(raw or ""),
        channel=channel,
        route_key=route_key or session_id,
        session_id=session_id,
        wants_voice=wants_voice,
    )
