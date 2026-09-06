"""Speech Output Adapter — reusable rendering for non-live voice paths.

Bot API, Telethon, and WebSocket all need the same thing: take planned
speech segments and produce a single WAV/OGG. This module is the single
place that does it, so the three call sites don't each re-implement
streaming-vs-monolithic logic.

V1: deterministic planner → per-segment streaming TTS (Fish primary,
ElevenLabs fallback) → 20ms PCM accumulation with pause_after_ms
silence → final WAV. Keeps the Telegram Bot API single-OGG contract
but improves synthesis internally.

Usage:
    from nally.voice.speech_output import render_to_wav
    wav_bytes = await render_to_wav(planned_text)
    # or for legacy sync call sites:
    # wav_bytes = await asyncio.to_thread(render_to_wav_sync, text)
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("nally.voice.speech_output")


def _silence_pcm(duration_ms: int, sample_rate: int = 48000) -> bytes:
    """Generate silence PCM (16-bit mono) for pause_after_ms."""
    samples = int(sample_rate * duration_ms / 1000)
    return b"\x00\x00" * samples


async def render_to_wav(
    text: str,
    profile: str = "nally",
    target_rate: int = 48000,
    user_sentiment: str | None = None,
) -> bytes | None:
    """Render text to WAV via SpeechPlanner + streaming TTS.

    Deterministic planner first, then per-segment streaming. Falls back
    to monolithic synthesis if streaming is unavailable. Returns WAV bytes
    or None on failure.
    """
    if not text or not text.strip():
        return None

    # Plan speech — deterministic, no LLM
    try:
        from .speech_planner import get_speech_planner

        planner = get_speech_planner(profile=profile)
        segments = planner.plan(text, user_sentiment=user_sentiment)
        if not segments:
            # Fallback to single segment if planner yields nothing
            from .speech_pipeline import SpeechSegment

            segments = [SpeechSegment(text=text, pause_after_ms=0)]
    except Exception as e:
        logger.warning(f"SpeechPlanner failed, falling back to plain text: {e}")
        from .speech_pipeline import SpeechSegment

        segments = [SpeechSegment(text=text, pause_after_ms=0)]

    # TTS backend — backend-agnostic, Fish primary for calls already handled
    # via get_backend() elsewhere; here we just use whatever is configured.
    try:
        from .tts import get_backend, _build_wav, _wav_to_pcm

        backend = get_backend()
    except Exception as e:
        logger.warning(f"TTS backend unavailable: {e}")
        return None

    # Accumulate PCM at target_rate
    pcm_accum = bytearray()

    for seg in segments:
        seg_text = seg.text.strip()
        if not seg_text:
            continue

        pcm_chunks: list[bytes] = []

        # Prefer streaming API if backend supports it
        stream_fn = getattr(backend, "synthesize_stream_pcm", None)
        if stream_fn is not None:
            try:
                # synthesize_stream_pcm is async generator
                async for chunk in stream_fn(seg_text, target_rate):
                    if chunk:
                        pcm_chunks.append(chunk)
            except Exception as e:
                logger.debug(f"Streaming failed for segment, falling back: {e}")
                pcm_chunks = []

        # Fallback: monolithic WAV then decode to PCM
        if not pcm_chunks:
            try:
                wav = await asyncio.to_thread(backend.synthesize_to_wav, seg_text)
                if wav:
                    pcm, sr = _wav_to_pcm(wav)
                    # Resample if needed (target_rate vs wav rate)
                    if sr != target_rate:
                        from .tts import _resample_pcm

                        pcm = _resample_pcm(pcm, sr, target_rate).tobytes()
                    else:
                        pcm = pcm.tobytes() if hasattr(pcm, "tobytes") else pcm
                    pcm_chunks.append(pcm)
            except Exception as e:
                logger.warning(f"TTS fallback failed for segment '{seg_text[:40]}': {e}")
                continue

        for chunk in pcm_chunks:
            pcm_accum.extend(chunk)

        # Insert pause from planner (deterministic, not TTS-driven)
        pause = getattr(seg, "pause_after_ms", 0)
        if pause and pause > 0:
            # Clamp to avoid excessive silence on long pauses
            pause = min(pause, 800)
            pcm_accum.extend(_silence_pcm(pause, target_rate))

    if not pcm_accum:
        return None

    # Build final WAV at target_rate
    try:
        from .tts import _build_wav

        # _build_wav expects PCM bytes and sample rate
        import numpy as np

        pcm_array = np.frombuffer(bytes(pcm_accum), dtype=np.int16)
        return _build_wav(pcm_array.tobytes(), target_rate)
    except Exception as e:
        logger.warning(f"Failed to build WAV: {e}")
        return None


def render_to_wav_sync(
    text: str,
    profile: str = "nally",
    target_rate: int = 48000,
    user_sentiment: str | None = None,
) -> bytes | None:
    """Synchronous wrapper for call sites that use to_thread already."""
    try:
        # If we're already in an event loop, run in a new thread
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop and loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor() as pool:
                return pool.submit(asyncio.run, render_to_wav(text, profile, target_rate, user_sentiment)).result()
        return asyncio.run(render_to_wav(text, profile, target_rate, user_sentiment))
    except Exception as e:
        logger.warning(f"render_to_wav_sync failed: {e}")
        return None
