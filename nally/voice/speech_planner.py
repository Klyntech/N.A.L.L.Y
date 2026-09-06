"""Speech Planner — public voice interface for Nally.

New public entry point for all voice paths. Wraps the underlying
analysis engine (speech_pipeline) so the engine can be refactored
without touching call sites.

Architecture:
    LLM text → VoiceFormatter (visual artifacts stripped)
            → SpeechPlanner (sentence cuts, pauses, pacing, emphasis,
               pronunciation, emotion metadata)
            → SpeechSegment[] (text + rate/pitch/volume/pause_after_ms)
            → TTS backend (Fish/ElevenLabs/Piper) → 20ms PCM

The planner is deterministic (no extra LLM) for V1. Per-emotion
voice-settings overrides are deferred to V2.

Usage:
    from nally.voice.speech_planner import SpeechPlanner
    planner = SpeechPlanner(profile="nally")
    segments = planner.plan(text, user_sentiment="neutral")
    # pass segment.text (or the segment list) downstream
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

from .speech_pipeline import (
    SpeechSegment as _EngineSegment,
    detect_user_sentiment,
    process_for_speech,
    process_for_speech_flat,
    split_into_sentences,
)


# Re-export segment type so callers don't import the engine directly.
SpeechSegment = _EngineSegment


class SpeechPlanner:
    """Stable public speech-planning interface.

    Wraps speech_pipeline as the underlying analysis engine. Call sites
    (bot voice notes, Telegram calls, LiveKit, WebSocket) depend only on
    this class — the engine may be replaced without touching them.
    """

    def __init__(self, profile: str = "nally"):
        self.profile = profile

    def plan(
        self,
        text: str,
        user_sentiment: str | None = None,
    ) -> List[SpeechSegment]:
        """Plan speech for text.

        Returns a list of SpeechSegment objects, each with text, rate,
        pitch, volume, pause_after_ms, and emotion. The list is ready for
        a streaming TTS backend; callers that only need plain strings can
        use plan_flat() or join segment texts.
        """
        return process_for_speech(text, profile=self.profile, user_sentiment=user_sentiment)

    def plan_flat(
        self,
        text: str,
        user_sentiment: str | None = None,
    ) -> List[str]:
        """Plan speech, returning only the spoken text per segment."""
        return process_for_speech_flat(text, profile=self.profile, user_sentiment=user_sentiment)

    def detect_sentiment(self, user_message: str) -> str:
        """Detect user sentiment for carrying into plan()."""
        return detect_user_sentiment(user_message)

    def split(self, text: str) -> List[str]:
        """Split text into sentences using the engine's boundary rules."""
        return split_into_sentences(text)


# Convenience singleton — mirrors get_backend() pattern for call sites
# that don't need a custom profile.
_default_planner: SpeechPlanner | None = None


def get_speech_planner(profile: str = "nally") -> SpeechPlanner:
    """Return a SpeechPlanner. Caches the default-profile instance."""
    global _default_planner
    if profile == "nally" and _default_planner is not None:
        return _default_planner
    planner = SpeechPlanner(profile=profile)
    if profile == "nally":
        _default_planner = planner
    return planner
