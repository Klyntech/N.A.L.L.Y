"""Text-to-speech using Piper (local, no API key).

Voice model is downloaded on first run and cached in data/voice/.
To swap to ElevenLabs / Groq TTS later, only this file changes.
"""

import io
import logging
import struct
import urllib.request
from pathlib import Path

import numpy as np

logger = logging.getLogger("nally.voice.tts")

VOICE_DIR = Path(__file__).parent.parent.parent / "data" / "voice"
DEFAULT_VOICE = "en_US-lessac-medium"

# Loaded once at module level
_voice = None

_VOICE_BASE_URL = (
    "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
)


def _ensure_voice():
    """Download the default Piper voice if not already cached."""
    VOICE_DIR.mkdir(parents=True, exist_ok=True)

    model_path = VOICE_DIR / f"{DEFAULT_VOICE}.onnx"
    config_path = VOICE_DIR / f"{DEFAULT_VOICE}.onnx.json"

    if model_path.exists() and config_path.exists():
        return model_path

    for filename in [f"{DEFAULT_VOICE}.onnx", f"{DEFAULT_VOICE}.onnx.json"]:
        dest = VOICE_DIR / filename
        if not dest.exists():
            url = f"{_VOICE_BASE_URL}/{filename}"
            logger.info(f"Downloading Piper voice: {filename} ...")
            urllib.request.urlretrieve(url, str(dest))
            logger.info(f"Downloaded {filename}")

    return model_path


def _get_voice():
    """Lazy-load the Piper voice model on first use."""
    global _voice
    if _voice is None:
        from piper import PiperVoice

        model_path = _ensure_voice()
        logger.info(f"Loading Piper voice: {DEFAULT_VOICE} ...")
        _voice = PiperVoice.load(str(model_path))
        logger.info("Piper voice loaded.")
    return _voice


def speak(text: str) -> None:
    """Speak *text* aloud through the default audio output.

    Synthesizes via Piper, then plays via sounddevice. Blocks until playback
    finishes. On failure, prints the text as a fallback.
    """
    if not text or not text.strip():
        return

    try:
        import sounddevice as sd

        voice = _get_voice()

        # Synthesize to raw 16-bit PCM
        audio_chunks = []
        for chunk in voice.synthesize(text):
            audio_chunks.append(chunk.audio_int16_bytes)

        raw = b"".join(audio_chunks)
        audio_int16 = np.frombuffer(raw, dtype=np.int16)
        audio_f32 = audio_int16.astype(np.float32) / 32768.0

        sd.play(audio_f32, samplerate=voice.config.sample_rate)
        sd.wait()

        logger.debug(f"Spoke: {text[:100]}")

    except Exception as e:
        logger.error(f"TTS failed: {e}")
        # Fallback: just print so the user still gets the response
        print(f"[TTS unavailable] {text}")


def synthesize_to_wav(text: str) -> bytes | None:
    """Synthesize text to WAV bytes (16-bit PCM, mono).

    Returns raw WAV file bytes suitable for browser AudioContext.decodeAudioData(),
    or None on failure.
    """
    if not text or not text.strip():
        return None

    try:
        voice = _get_voice()

        # Synthesize to raw 16-bit PCM
        audio_chunks = []
        for chunk in voice.synthesize(text):
            audio_chunks.append(chunk.audio_int16_bytes)

        raw = b"".join(audio_chunks)
        sample_rate = voice.config.sample_rate

        # Build WAV file in memory
        buf = io.BytesIO()
        num_samples = len(raw) // 2  # int16 = 2 bytes each
        data_size = num_samples * 2

        # RIFF header
        buf.write(b"RIFF")
        buf.write(struct.pack("<I", 36 + data_size))
        buf.write(b"WAVE")
        # fmt chunk
        buf.write(b"fmt ")
        buf.write(struct.pack("<I", 16))          # chunk size
        buf.write(struct.pack("<H", 1))           # PCM format
        buf.write(struct.pack("<H", 1))           # mono
        buf.write(struct.pack("<I", sample_rate))  # sample rate
        buf.write(struct.pack("<I", sample_rate * 2))  # byte rate
        buf.write(struct.pack("<H", 2))           # block align
        buf.write(struct.pack("<H", 16))          # bits per sample
        # data chunk
        buf.write(b"data")
        buf.write(struct.pack("<I", data_size))
        buf.write(raw)

        wav_bytes = buf.getvalue()
        logger.debug(f"Synthesized WAV: {len(wav_bytes)} bytes, {num_samples / sample_rate:.1f}s")
        return wav_bytes

    except Exception as e:
        logger.error(f"TTS synthesis failed: {e}")
        return None
