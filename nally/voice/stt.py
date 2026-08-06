"""Speech-to-text with fallback chain: Groq API → faster-whisper (local).

Groq Whisper: fast, accurate, free tier (10K req/month), needs internet.
faster-whisper: local fallback, no API key, ~150MB model download.
"""

import io
import logging
import struct

import numpy as np

logger = logging.getLogger("nally.voice.stt")

# Local model cache
_local_model = None


def _transcribe_groq(audio_bytes: bytes, sample_rate: int = 16000) -> str | None:
    """Transcribe via Groq Whisper API (fast, free)."""
    try:
        import requests

        try:
            from ..config import GROQ_API_KEY
        except ImportError:
            return None

        if not GROQ_API_KEY:
            return None

        wav_bytes = _pcm_to_wav(audio_bytes, sample_rate)

        resp = requests.post(
            "https://api.groq.com/openai/v1/audio/transcriptions",
            headers={"Authorization": f"Bearer {GROQ_API_KEY}"},
            files={"file": ("audio.wav", wav_bytes, "audio/wav")},
            data={"model": "whisper-large-v3-turbo", "response_format": "text"},
            timeout=30,
        )

        if resp.status_code == 200:
            text = resp.text.strip()
            logger.debug(f"Groq STT ({len(audio_bytes) / sample_rate / 4:.1f}s): {text[:120]}")
            return text
        else:
            logger.warning(f"Groq STT error {resp.status_code}: {resp.text[:200]}")
            return None

    except Exception as e:
        logger.warning(f"Groq STT failed: {e}")
        return None


def _transcribe_local(audio_bytes: bytes, sample_rate: int = 16000) -> str:
    """Transcribe via faster-whisper (local, no API key)."""
    global _local_model

    try:
        from faster_whisper import WhisperModel

        if _local_model is None:
            logger.info("Loading faster-whisper model (tiny)...")
            _local_model = WhisperModel("tiny", device="cpu", compute_type="int8")
            logger.info("faster-whisper model loaded.")

        audio = np.frombuffer(audio_bytes, dtype=np.float32)
        segments, _info = _local_model.transcribe(
            audio,
            beam_size=5,
            language="en",
            vad_filter=True,
        )

        text = " ".join(seg.text for seg in segments).strip()
        logger.debug(f"Local STT ({len(audio_bytes) / sample_rate:.1f}s): {text[:120]}")
        return text

    except Exception as e:
        logger.error(f"Local STT failed: {e}")
        return ""


def _pcm_to_wav(pcm_bytes: bytes, sample_rate: int) -> bytes:
    """Wrap raw PCM float32 in WAV header."""
    buf = io.BytesIO()
    num_samples = len(pcm_bytes) // 4
    data_size = num_samples * 2

    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", 16))
    buf.write(struct.pack("<H", 1))
    buf.write(struct.pack("<H", 1))
    buf.write(struct.pack("<I", sample_rate))
    buf.write(struct.pack("<I", sample_rate * 2))
    buf.write(struct.pack("<H", 2))
    buf.write(struct.pack("<H", 16))
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))

    audio = np.frombuffer(pcm_bytes, dtype=np.float32)
    audio_int16 = (audio * 32767).clip(-32768, 32767).astype(np.int16)
    buf.write(audio_int16.tobytes())

    return buf.getvalue()


def transcribe(audio_bytes: bytes, sample_rate: int = 16000) -> str:
    """Transcribe raw audio bytes to text.

    Tries Groq API first (fast, accurate), falls back to local faster-whisper.

    Args:
        audio_bytes: Raw PCM audio as float32 bytes, mono, at *sample_rate*.
        sample_rate: Sample rate of the audio (default 16000).

    Returns:
        Transcribed text, or empty string on failure.
    """
    if not audio_bytes or len(audio_bytes) < 1000:
        return ""

    result = _transcribe_groq(audio_bytes, sample_rate)
    if result is not None:
        return result

    logger.info("Using local STT fallback (faster-whisper)")
    return _transcribe_local(audio_bytes, sample_rate)
