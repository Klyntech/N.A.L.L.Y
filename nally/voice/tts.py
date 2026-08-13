"""Text-to-speech with swappable backends.

Piper (default): local, free, no API key.
ElevenLabs: premium cloud TTS, requires API key.

Backend is selected via NALLY_TTS_BACKEND env var.
Public API: speak(text), synthesize_to_wav(text)
"""

import io
import logging
import struct
import urllib.request
from pathlib import Path

import numpy as np

logger = logging.getLogger("nally.voice.tts")

# ── Backend registry ──────────────────────────────────────

_backends = {}
_active_backend = None


class TTSBackend:
    """Base class for TTS backends."""

    name: str = "base"

    def speak(self, text: str) -> None:
        raise NotImplementedError

    def synthesize_to_wav(self, text: str) -> bytes | None:
        raise NotImplementedError


# ── Piper backend (local, free) ──────────────────────────

VOICE_DIR = Path(__file__).parent.parent.parent / "data" / "voice"
DEFAULT_VOICE = "en_US-lessac-medium"
_VOICE_BASE_URL = "https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/lessac/medium"
_voice = None


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


class PiperBackend(TTSBackend):
    """Local Piper TTS — free, unlimited, decent quality."""

    name = "piper"

    def speak(self, text: str) -> None:
        if not text or not text.strip():
            return

        try:
            import sounddevice as sd

            voice = _get_voice()

            audio_chunks = []
            for chunk in voice.synthesize(text):
                audio_chunks.append(chunk.audio_int16_bytes)

            raw = b"".join(audio_chunks)
            audio_int16 = np.frombuffer(raw, dtype=np.int16)
            audio_f32 = audio_int16.astype(np.float32) / 32768.0

            sd.play(audio_f32, samplerate=voice.config.sample_rate)
            sd.wait()

            logger.debug(f"Piper spoke: {text[:100]}")

        except Exception as e:
            logger.error(f"Piper TTS failed: {e}")
            print(f"[TTS unavailable] {text}")

    def synthesize_to_wav(self, text: str) -> bytes | None:
        if not text or not text.strip():
            return None

        try:
            voice = _get_voice()

            audio_chunks = []
            for chunk in voice.synthesize(text):
                audio_chunks.append(chunk.audio_int16_bytes)

            raw = b"".join(audio_chunks)
            sample_rate = voice.config.sample_rate

            return _build_wav(raw, sample_rate)

        except Exception as e:
            logger.error(f"Piper synthesis failed: {e}")
            return None


# ── ElevenLabs backend (cloud, premium) ──────────────────


class ElevenLabsBackend(TTSBackend):
    """ElevenLabs cloud TTS — premium quality, requires API key."""

    name = "elevenlabs"

    def _get_config(self):
        from ..config import ELEVENLABS_API_KEY, ELEVENLABS_MODEL, ELEVENLABS_VOICE_ID

        if not ELEVENLABS_API_KEY:
            raise ValueError("ELEVENLABS_API_KEY not set")
        return ELEVENLABS_API_KEY, ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL

    def _tts_request(self, text: str, output_format: str = "mp3_44100_128") -> bytes | None:
        """Make a TTS request to ElevenLabs API."""
        try:
            api_key, voice_id, model = self._get_config()

            url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format={output_format}"
            payload = {
                "text": text,
                "model_id": model,
                "voice_settings": {
                    "stability": 0.65,
                    "similarity_boost": 0.80,
                    "style": 0.35,
                    "use_speaker_boost": True,
                },
            }

            data = __import__("json").dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                url,
                data=data,
                headers={
                    "xi-api-key": api_key,
                    "Content-Type": "application/json",
                },
            )

            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()

        except Exception as e:
            logger.error(f"ElevenLabs API error: {e}")
            return None

    def speak(self, text: str) -> None:
        if not text or not text.strip():
            return

        try:
            import sounddevice as sd

            mp3_bytes = self._tts_request(text, "mp3_44100_128")
            if not mp3_bytes:
                print(f"[TTS unavailable] {text}")
                return

            # Decode MP3 to PCM using ffmpeg
            pcm_data, sample_rate = _mp3_to_pcm(mp3_bytes)
            if pcm_data is None:
                print(f"[TTS unavailable] {text}")
                return

            audio_int16 = np.frombuffer(pcm_data, dtype=np.int16)
            audio_f32 = audio_int16.astype(np.float32) / 32768.0

            sd.play(audio_f32, samplerate=sample_rate)
            sd.wait()

            logger.debug(f"ElevenLabs spoke: {text[:100]}")

        except Exception as e:
            logger.error(f"ElevenLabs TTS failed: {e}")
            print(f"[TTS unavailable] {text}")

    def synthesize_to_wav(self, text: str) -> bytes | None:
        if not text or not text.strip():
            return None

        try:
            # Request raw PCM from ElevenLabs
            pcm_bytes = self._tts_request(text, "pcm_22050")
            if not pcm_bytes:
                return None

            # ElevenLabs returns raw PCM — wrap in WAV header
            return _build_wav(pcm_bytes, 22050)

        except Exception as e:
            logger.error(f"ElevenLabs synthesis failed: {e}")
            return None

    def synthesize_to_ogg(self, text: str) -> bytes | None:
        """Synthesize text directly to OGG/Opus for Telegram."""
        if not text or not text.strip():
            return None

        try:
            mp3_bytes = self._tts_request(text, "mp3_44100_128")
            if not mp3_bytes:
                return None

            return _mp3_to_ogg(mp3_bytes)

        except Exception as e:
            logger.error(f"ElevenLabs OGG synthesis failed: {e}")
            return None


# ── Helpers ───────────────────────────────────────────────


def _build_wav(pcm_int16: bytes, sample_rate: int) -> bytes:
    """Wrap raw int16 PCM in a WAV header."""
    buf = io.BytesIO()
    num_samples = len(pcm_int16) // 2
    data_size = num_samples * 2

    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", 16))
    buf.write(struct.pack("<H", 1))  # PCM
    buf.write(struct.pack("<H", 1))  # mono
    buf.write(struct.pack("<I", sample_rate))
    buf.write(struct.pack("<I", sample_rate * 2))
    buf.write(struct.pack("<H", 2))
    buf.write(struct.pack("<H", 16))
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(pcm_int16)

    return buf.getvalue()


def _mp3_to_pcm(mp3_bytes: bytes, sample_rate: int = 22050) -> tuple[bytes | None, int]:
    """Decode MP3 to raw int16 PCM via ffmpeg."""
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("ffmpeg"):
        logger.error("ffmpeg not installed — required for MP3 decoding")
        return None, sample_rate

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_in:
        tmp_in.write(mp3_bytes)
        tmp_in_path = tmp_in.name

    tmp_out_path = tmp_in_path.replace(".mp3", ".pcm")

    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", tmp_in_path,
                "-f", "s16le",
                "-acodec", "pcm_s16le",
                "-ar", str(sample_rate),
                "-ac", "1",
                tmp_out_path,
            ],
            capture_output=True,
            timeout=30,
        )

        if proc.returncode != 0:
            logger.error(f"ffmpeg MP3->PCM failed: {proc.stderr.decode()[:200]}")
            return None, sample_rate

        pcm_bytes = Path(tmp_out_path).read_bytes()
        return pcm_bytes, sample_rate

    finally:
        for p in [tmp_in_path, tmp_out_path]:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass


def _mp3_to_ogg(mp3_bytes: bytes) -> bytes | None:
    """Convert MP3 to OGG/Opus via ffmpeg (for Telegram)."""
    import shutil
    import subprocess
    import tempfile

    if not shutil.which("ffmpeg"):
        logger.error("ffmpeg not installed — required for OGG conversion")
        return None

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp_in:
        tmp_in.write(mp3_bytes)
        tmp_in_path = tmp_in.name

    tmp_out_path = tmp_in_path.replace(".mp3", ".ogg")

    try:
        proc = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", tmp_in_path,
                "-c:a", "libopus",
                "-b:a", "96k",
                "-application", "audio",
                tmp_out_path,
            ],
            capture_output=True,
            timeout=30,
        )

        if proc.returncode != 0:
            logger.error(f"ffmpeg MP3->OGG failed: {proc.stderr.decode()[:200]}")
            return None

        return Path(tmp_out_path).read_bytes()

    finally:
        for p in [tmp_in_path, tmp_out_path]:
            try:
                Path(p).unlink(missing_ok=True)
            except OSError:
                pass


def _strip_markdown(text: str) -> str:
    """Light preprocessing: only strip markdown formatting.

    Used for ElevenLabs which handles pronunciation and normalization natively.
    The full preprocess_for_speech pipeline (pronunciation map, number expansion,
    etc.) corrupts ElevenLabs output — it knows how to say "Python" correctly.
    """
    if not text:
        return ""
    import re
    # Strip code blocks
    text = re.sub(r"```[\s\S]*?```", "", text)
    # Strip inline code
    text = re.sub(r"`([^`]+)`", r"\1", text)
    # Strip bold/italic/strikethrough
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
    text = re.sub(r"\*([^*]+)\*", r"\1", text)
    text = re.sub(r"~~([^~]+)~~", r"\1", text)
    # Strip headers
    text = re.sub(r"#{1,6}\s+", "", text)
    # Strip list bullets
    text = re.sub(r"[-*]\s+", "", text)
    # Links → text only
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    # Clean residual markdown
    text = re.sub(r"[#*_~`|<>]", "", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


# ── Public API ────────────────────────────────────────────


def get_backend() -> TTSBackend:
    """Get the active TTS backend (lazy singleton)."""
    global _active_backend

    if _active_backend is not None:
        return _active_backend

    try:
        from ..config import TTS_BACKEND
    except ImportError:
        TTS_BACKEND = "piper"

    if TTS_BACKEND == "elevenlabs":
        try:
            from ..config import ELEVENLABS_API_KEY

            if not ELEVENLABS_API_KEY:
                logger.warning("ELEVENLABS_API_KEY not set — falling back to Piper")
                _active_backend = PiperBackend()
            else:
                _active_backend = ElevenLabsBackend()
                logger.info("Using ElevenLabs TTS backend")
        except Exception as e:
            logger.warning(f"ElevenLabs init failed ({e}) — falling back to Piper")
            _active_backend = PiperBackend()
    else:
        _active_backend = PiperBackend()
        logger.info("Using Piper TTS backend")

    return _active_backend


def speak(text: str) -> None:
    """Speak text aloud through the active TTS backend.

    Preprocessing is backend-aware:
    - Piper: full pipeline (pronunciation map, normalization)
    - ElevenLabs: markdown strip only (it handles pronunciation natively)
    """
    from .speech_pipeline import preprocess_for_speech

    if not text or not text.strip():
        return

    backend = get_backend()
    if backend.name == "elevenlabs":
        processed = _strip_markdown(text)
    else:
        processed = preprocess_for_speech(text)
    backend.speak(processed)


def synthesize_to_wav(text: str) -> bytes | None:
    """Synthesize text to WAV bytes (16-bit PCM, mono).

    Preprocessing is backend-aware (same as speak()).
    """
    from .speech_pipeline import preprocess_for_speech

    if not text or not text.strip():
        return None

    backend = get_backend()
    if backend.name == "elevenlabs":
        processed = _strip_markdown(text)
    else:
        processed = preprocess_for_speech(text)
    return backend.synthesize_to_wav(processed)
