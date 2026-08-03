"""Speech-to-text using faster-whisper (local, no API key).

Model is loaded once at module level — "small" for speed/quality balance.
To swap to Groq Whisper later, only this file changes.
"""

import logging

import numpy as np

logger = logging.getLogger("nally.voice.stt")

# Loaded once at module level
_model = None


def _get_model():
    """Lazy-load the faster-whisper model on first use."""
    global _model
    if _model is None:
        from faster_whisper import WhisperModel

        logger.info("Loading faster-whisper model (small)...")
        _model = WhisperModel("small", device="cpu", compute_type="int8")
        logger.info("faster-whisper model loaded.")
    return _model


def transcribe(audio_bytes: bytes, sample_rate: int = 16000) -> str:
    """Transcribe raw audio bytes to text.

    Args:
        audio_bytes: Raw PCM audio as float32 bytes, mono, at *sample_rate*.
        sample_rate: Sample rate of the audio (default 16000).

    Returns:
        Transcribed text, or empty string on failure.
    """
    try:
        model = _get_model()
        audio = np.frombuffer(audio_bytes, dtype=np.float32)

        segments, _info = model.transcribe(
            audio,
            beam_size=5,
            language="en",
            vad_filter=True,
        )

        text = " ".join(seg.text for seg in segments).strip()
        logger.debug(f"Transcribed ({len(audio) / sample_rate:.1f}s): {text[:120]}")
        return text

    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return ""
