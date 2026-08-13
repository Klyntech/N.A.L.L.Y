"""Telegram Voice Helpers — OGG/Opus conversion for Telegram voice messages.

Telegram requires OGG/Opus for voice messages. This module handles:
- Downloading voice files from Telegram
- Converting OGG/Opus to raw PCM for STT
- Converting WAV to OGG/Opus for sending back
"""

import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger("nally.telegram.voice")

# Telegram voice message specs
TELEGRAM_SAMPLE_RATE = 48000  # Telegram uses 48kHz for voice
STT_SAMPLE_RATE = 16000  # Whisper expects 16kHz


def ogg_to_pcm(ogg_bytes: bytes, sample_rate: int = STT_SAMPLE_RATE) -> bytes | None:
    """Convert OGG/Opus bytes to raw PCM (float32) for STT.

    Args:
        ogg_bytes: Raw OGG/Opus audio bytes from Telegram.
        sample_rate: Target sample rate (default 16000 for Whisper).

    Returns:
        Raw PCM bytes as float32, or None on failure.
    """
    try:
        import shutil
        if not shutil.which("ffmpeg"):
            logger.error("ffmpeg not installed — required for voice conversion")
            return None

        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp_in:
            tmp_in.write(ogg_bytes)
            tmp_in_path = tmp_in.name

        tmp_out_path = tmp_in_path.replace(".ogg", ".pcm")

        try:
            proc = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-i", tmp_in_path,
                    "-f", "f32le",
                    "-acodec", "pcm_f32le",
                    "-ar", str(sample_rate),
                    "-ac", "1",
                    tmp_out_path,
                ],
                capture_output=True,
                timeout=30,
            )

            if proc.returncode != 0:
                logger.error(f"ffmpeg OGG->PCM failed: {proc.stderr.decode()[:200]}")
                return None

            pcm_bytes = Path(tmp_out_path).read_bytes()
            logger.debug(f"Converted OGG->PCM: {len(ogg_bytes)} -> {len(pcm_bytes)} bytes")
            return pcm_bytes

        finally:
            for p in [tmp_in_path, tmp_out_path]:
                try:
                    Path(p).unlink(missing_ok=True)
                except OSError:
                    pass

    except Exception as e:
        logger.error(f"OGG to PCM conversion failed: {e}")
        return None


def wav_to_ogg(wav_bytes: bytes) -> bytes | None:
    """Convert WAV bytes to OGG/Opus for Telegram voice message.

    Args:
        wav_bytes: WAV file bytes (from Piper synthesize_to_wav).

    Returns:
        OGG/Opus bytes, or None on failure.
    """
    try:
        import shutil
        if not shutil.which("ffmpeg"):
            logger.error("ffmpeg not installed — required for voice conversion")
            return None

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_in:
            tmp_in.write(wav_bytes)
            tmp_in_path = tmp_in.name

        tmp_out_path = tmp_in_path.replace(".wav", ".ogg")

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
                logger.error(f"ffmpeg WAV->OGG failed: {proc.stderr.decode()[:200]}")
                return None

            ogg_bytes = Path(tmp_out_path).read_bytes()
            logger.debug(f"Converted WAV->OGG: {len(wav_bytes)} -> {len(ogg_bytes)} bytes")
            return ogg_bytes

        finally:
            for p in [tmp_in_path, tmp_out_path]:
                try:
                    Path(p).unlink(missing_ok=True)
                except OSError:
                    pass

    except Exception as e:
        logger.error(f"WAV to OGG conversion failed: {e}")
        return None


def check_ffmpeg() -> bool:
    """Check if ffmpeg is available."""
    try:
        import shutil
        return shutil.which("ffmpeg") is not None
    except Exception:
        return False
