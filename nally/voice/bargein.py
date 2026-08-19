"""Barge-In Detector — turn-taking with a configurable grace period.

The detector combines VAD (speech onset) with partial-transcript content
analysis to decide when a user is genuinely interrupting Nally's speech.

Policy:
  - While Nally is speaking, a VAD speech onset starts a grace timer.
  - If sustained speech (past BARGEIN_GRACE_MS) carries a *content word*
    (not just a backchannel like "uh", "ok"), the interruption is confirmed.
  - The grace period prevents cutting off brief noises / natural backchannels.

Metrics: increments bargein_events_total and records onset-to-confirm latency.
"""

from __future__ import annotations

import re
import time
from typing import Optional

from .metrics import inc_bargein

# Standard backchannel / filler words that should NOT trigger barge-in
_FILLER_WORDS = {
    "um", "uh", "ah", "er", "mhm", "huh", "yeah", "ok", "okay", "yep",
    "yup", "yes", "oh", "like", "mm", "hmm", "right", "sure", "gotcha",
}


def has_content_word(text: str) -> bool:
    """Return True if *text* contains a meaningful word (not just fillers)."""
    cleaned = re.sub(r"[^\w\s]", "", text.lower()).strip()
    words = cleaned.split()
    if not words:
        return False
    for word in words:
        if word not in _FILLER_WORDS and len(word) > 1:
            return True
    return False


class BargeInDetector:
    """State machine for detecting user interruptions during TTS playback."""

    def __init__(self, grace_ms: int = 200, vad_threshold: float = 0.5):
        self.grace_ms = max(0, grace_ms)
        self.vad_threshold = vad_threshold
        self.agent_speaking = False

        # VAD / speech-onset state
        self._vad_onset_time: Optional[float] = None
        self._grace_end_time: Optional[float] = None
        self._content_word_seen = False

    # ── Lifecycle ──

    def set_agent_speaking(self, speaking: bool):
        """Mark whether Nally is currently generating/playing audio."""
        self.agent_speaking = speaking
        if not speaking:
            # Reset everything once Nally stops talking.
            self._vad_onset_time = None
            self._grace_end_time = None
            self._content_word_seen = False

    # ── VAD feed (from Silero, called per audio chunk) ──

    def on_vad(self, prob: float) -> None:
        """Feed a VAD probability (0..1). Records speech onset while speaking."""
        if not self.agent_speaking:
            return
        now = time.time()
        if prob > self.vad_threshold:
            if self._vad_onset_time is None:
                self._vad_onset_time = now
                self._grace_end_time = now + (self.grace_ms / 1000.0)
        else:
            # VAD dropped — if no content word confirmed yet, reset onset.
            if not self._content_word_seen:
                self._vad_onset_time = None
                self._grace_end_time = None

    # ── Transcript feed (from streaming STT, called on partials) ──

    def on_partial(self, text: str) -> bool:
        """Process a partial transcript. Returns True if barge-in is confirmed.

        Confirmation requires: agent speaking, a prior VAD onset, a content
        word, and the grace period to have elapsed.
        """
        if not self.agent_speaking or self._vad_onset_time is None:
            return False
        if not has_content_word(text):
            return False

        self._content_word_seen = True
        if time.time() >= (self._grace_end_time or 0):
            return True
        return False

    # ── Confirmation ──

    def confirm_interrupt(self) -> dict:
        """Finalize an interruption, record metrics, and reset state."""
        onset = self._vad_onset_time or time.time()
        latency_ms = (time.time() - onset) * 1000.0

        metrics = {
            "type": "barge_in",
            "latency_ms": round(latency_ms, 1),
            "user_audio_start": onset,
            "confirmed_at": time.time(),
            "grace_ms": self.grace_ms,
        }

        try:
            inc_bargein({"grace_ms": str(self.grace_ms)})
        except Exception:
            pass

        self._vad_onset_time = None
        self._grace_end_time = None
        self._content_word_seen = False
        return metrics

    def reset(self):
        """Reset all VAD / content-word state (e.g. on new turn)."""
        self._vad_onset_time = None
        self._grace_end_time = None
        self._content_word_seen = False
