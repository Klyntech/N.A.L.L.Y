"""Barge-In Detector — evaluates VAD signals and partial transcripts to detect user interruption."""

import re
import time
from typing import Optional

def has_content_word(text: str) -> bool:
    """Check if the transcribed text contains any meaningful content words (not just fillers)."""
    cleaned = re.sub(r"[^\w\s]", "", text.lower()).strip()
    words = cleaned.split()
    if not words:
        return False
    
    # Standard backchannel and filler words that should not trigger barge-in
    filler_words = {"um", "uh", "ah", "er", "mhm", "huh", "yeah", "ok", "okay", "yep", "yes", "oh", "like"}
    for word in words:
        if word not in filler_words and len(word) > 1:
            return True
    return False

class BargeInDetector:
    def __init__(self):
        self.agent_speaking = False
        self.vad_onset_time: Optional[float] = None
        self.content_word_seen = False

    def on_vad(self, prob: float):
        """Update VAD probability and track speech onset time when agent is talking."""
        if prob > 0.5:
            if self.agent_speaking and self.vad_onset_time is None:
                self.vad_onset_time = time.time()
        else:
            # If VAD drops back down and no content word was seen, reset (likely a brief noise or backchannel)
            if not self.content_word_seen:
                self.vad_onset_time = None

    def on_partial(self, text: str) -> Optional[str]:
        """Process partial transcript. Returns 'barge_in_confirmed' if interruption is real."""
        if not self.agent_speaking or not self.vad_onset_time:
            return None

        if has_content_word(text):
            self.content_word_seen = True
            return "barge_in_confirmed"
        return None

    def confirm_interrupt(self) -> dict:
        """Reset state and return interruption metrics."""
        onset = self.vad_onset_time or time.time()
        now = time.time()
        latency_ms = (now - onset) * 1000.0

        metrics = {
            "type": "barge_in",
            "latency_ms": latency_ms,
            "user_audio_start": onset,
            "confirmed_at": now
        }

        # Reset states
        self.vad_onset_time = None
        self.content_word_seen = False
        return metrics

    def reset(self):
        """Reset VAD and content word states."""
        self.vad_onset_time = None
        self.content_word_seen = False
