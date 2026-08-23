"""VoicePipeline — overlapped streaming STT → TTS orchestrator.

Runs three concurrent asyncio workers so inbound audio is transcribed while
outbound audio is still being synthesized/played (true overlap):

  1. STT ingest  : resample 48k->16k, stream to Deepgram, run Silero VAD.
  2. TTS synth   : pull final transcripts, stream Fish Audio TTS to outbound queue.
  3. Barge-in    : watch interim transcripts, confirm user interruptions.

Audio contract:
  - feed_audio(frame)      : raw int16 PCM @ 48000 Hz (Telegram call rate).
  - get_output_frame()      : raw int16 PCM @ 48000 Hz (for pytgcalls send_frame).

Back-pressure is handled with bounded queues (oldest dropped under load).
All latency/error metrics flow through nally.voice.metrics.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time

import numpy as np

from .bargein import BargeInDetector
from .metrics import (
    inc_error,
    inc_frames,
    record_pipeline_latency,
    record_tts_latency,
)

logger = logging.getLogger("nally.voice.pipeline")

# Telegram voice chat runs at 48 kHz; Deepgram expects 16 kHz.
CALL_SAMPLE_RATE = 48000
STT_SAMPLE_RATE = 16000

# Silero VAD needs >= 512 samples @16k => 1536 samples @48k.
VAD_MIN_SAMPLES_48K = 1536

# Module-level VAD singleton — loaded once, reused across calls.
_vad_model = None
_vad_loaded = False


def resample_pcm(pcm_int16: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Resample raw int16 mono PCM using high-quality polyphase.

    Telegram capture is 48k, Deepgram expects 16k (3:1).  Linear interp is
    hoarse and aliases — use soxr/scipy when available.
    Mirrors nally.voice.tts._resample_pcm but kept local to avoid import cycle.
    """
    if src_rate == dst_rate or not pcm_int16:
        return pcm_int16
    audio_len = len(pcm_int16) // 2
    if audio_len < 2:
        return pcm_int16
    # Try soxr (HQ)
    try:
        import soxr  # type: ignore

        audio_f32 = np.frombuffer(pcm_int16, dtype=np.int16).astype(np.float32) / 32768.0
        out_f32 = soxr.resample(audio_f32, src_rate, dst_rate, quality="HQ")
        out_f32 = np.clip(out_f32, -1.0, 1.0)
        return (out_f32 * 32767).astype(np.int16).tobytes()
    except ImportError:
        pass
    except Exception:
        pass
    # Try scipy polyphase
    try:
        from scipy.signal import resample_poly  # type: ignore
        import math

        audio = np.frombuffer(pcm_int16, dtype=np.int16).astype(np.float32)
        g = math.gcd(int(src_rate), int(dst_rate))
        up = int(dst_rate // g)
        down = int(src_rate // g)
        resampled = resample_poly(audio, up, down, window=("kaiser", 5.0))
        expected = int(round(len(audio) * dst_rate / src_rate))
        if len(resampled) > expected:
            resampled = resampled[:expected]
        elif len(resampled) < expected:
            resampled = np.pad(resampled, (0, expected - len(resampled)))
        return np.clip(resampled, -32768, 32767).astype(np.int16).tobytes()
    except ImportError:
        pass
    except Exception:
        pass
    # Fallback linear
    audio = np.frombuffer(pcm_int16, dtype=np.int16).astype(np.float32)
    n_dst = int(round(len(audio) * dst_rate / src_rate))
    if n_dst <= 0:
        return b""
    resampled = np.interp(
        np.linspace(0, len(audio) - 1, n_dst), np.arange(len(audio)), audio
    )
    return np.clip(resampled, -32768, 32767).astype(np.int16).tobytes()


class VoicePipeline:
    """Async orchestrator tying streaming STT, TTS, and barge-in together."""

    def __init__(
        self,
        stt,
        tts,
        bargein: BargeInDetector | None = None,
        sample_rate: int = CALL_SAMPLE_RATE,
        stt_sample_rate: int = STT_SAMPLE_RATE,
        outbound_queue_size: int = 600,
        inbound_queue_size: int = 200,
        on_bargein=None,
        on_transcript=None,
    ):
        self.stt = stt
        self.tts = tts
        self.bargein = bargein or BargeInDetector()
        self.sample_rate = sample_rate
        self.stt_sample_rate = stt_sample_rate

        self._inbound: asyncio.Queue[bytes] = asyncio.Queue(maxsize=inbound_queue_size)
        self._outbound: asyncio.Queue[bytes] = asyncio.Queue(maxsize=outbound_queue_size)

        self._running = False
        self._tasks: list[asyncio.Task] = []
        self._vad_model = None
        self._bargein_event = asyncio.Event()
        self._tts_cancel = asyncio.Event()
        self.on_bargein = on_bargein  # optional callable(metrics)
        # Async callable(text) -> response text. If None, the transcript itself
        # is echoed back (useful for tests/offline).
        self.on_transcript = on_transcript

        # VAD accumulation buffer (raw 48k frames)
        self._vad_buffer: list[bytes] = []
        self._vad_samples = 0
        self._last_queue_full_log: float = 0.0

    # ── Lifecycle ──

    async def start(self) -> bool:
        """Connect STT, load VAD, and spawn worker tasks. Returns connected."""
        if self._running:
            return True

        # 1. Load Silero VAD FIRST — before opening Deepgram, so the socket
        # doesn't sit idle for 15-20s while torch loads the model (NET-0001).
        # This is the root cause of the 19s gap in the logs.
        global _vad_model, _vad_loaded
        if not _vad_loaded:
            try:
                from silero_vad import load_silero_vad
                _vad_model = await asyncio.to_thread(load_silero_vad, onnx=True)
                _vad_loaded = True
                logger.info("silero_vad_loaded")
            except Exception as e:
                logger.warning("silero_vad_load_failed", extra={"error": str(e)})
                _vad_loaded = True  # Don't retry
        self._vad_model = _vad_model

        # 2. Connect STT — now workers can send audio immediately after connect
        stt_ok = await self.stt.connect()
        if not stt_ok:
            inc_error("stt_connect")
            logger.error("pipeline_stt_unavailable", extra={"action": "transcription_disabled"})

        self._running = True
        self._tasks = [
            asyncio.create_task(self._stt_ingest_worker(), name="stt-ingest"),
            asyncio.create_task(self._tts_synth_worker(), name="tts-synth"),
            asyncio.create_task(self._bargein_monitor(), name="bargein"),
        ]
        logger.info("pipeline_started")
        return stt_ok

    async def stop(self):
        """Cancel workers and close STT."""
        self._running = False
        for task in self._tasks:
            if not task.done():
                task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self._tasks.clear()
        with contextlib.suppress(Exception):
            await self.stt.close()
        logger.info("pipeline_stopped")

    # ── Public I/O ──

    def feed_audio(self, frame_bytes: bytes):
        """Feed one inbound audio frame (raw int16 PCM @ sample_rate).

        Non-blocking; drops the frame if the inbound queue is full or STT
        is disconnected and not reconnecting. Safe to call from the pytgcalls
        callback thread via run_coroutine_threadsafe.
        """
        if not self._running or not frame_bytes:
            return
        # Allow frames during reconnect — queue them instead of dropping
        if not self.stt.connected and not getattr(self.stt, '_reconnecting', False):
            if not hasattr(self, '_stt_drop_logged'):
                self._stt_drop_logged = True
                logger.warning("stt_disconnected", extra={"action": "dropping_frames"})
            return
        try:
            self._inbound.put_nowait(frame_bytes)
            inc_frames(1)
        except asyncio.QueueFull:
            now = time.monotonic()
            if now - self._last_queue_full_log >= 12.0:
                self._last_queue_full_log = now
                logger.debug("inbound_queue_full", extra={"action": "dropping_frame"})

    def get_output_frame(self) -> bytes | None:
        """Pull the next synthesized audio frame (raw int16 PCM @ sample_rate).

        Returns None if no frame is ready. Caller (session) is responsible for
        sending it to the transport (pytgcalls send_frame).
        """
        try:
            return self._outbound.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def speak(self, text: str):
        """Synthesize *text* immediately and stream it to the outbound queue.

        Bypasses the transcript→agent path (used for greetings, prompts).
        """
        if not text or not text.strip():
            return
        await self._synthesize_turn(text)

    def clear_output(self):
        """Discard any pending outbound audio (used on barge-in)."""
        while not self._outbound.empty():
            try:
                self._outbound.get_nowait()
            except asyncio.QueueEmpty:
                break

    @property
    def running(self) -> bool:
        return self._running

    # ── Worker 1: STT ingest + VAD ──

    async def _stt_ingest_worker(self):
        _frames_logged = 0
        while self._running:
            try:
                frame = await self._inbound.get()
            except asyncio.CancelledError:
                raise

            # Clinton debug tip: log size + first bytes of every frame so we can
            # confirm real audio is arriving (and catch empty/invalid frames).
            if _frames_logged < 3:
                _frames_logged += 1
                preview = frame[:8].hex() if frame else "empty"
                logger.info(
                    "pipeline_frame",
                    extra={
                        "frame_bytes": len(frame),
                        "preview_hex": preview,
                        "sample_rate": self.sample_rate,
                        "expected_48k": self.sample_rate == 48000,
                    },
                )
            # Guard empty frames — never send empty bytes to Deepgram, they don't
            # reset the idle timer and can be treated as invalid.
            if not frame or len(frame) == 0:
                continue

            # Resample 48k -> 16k for Deepgram.
            # Ensure resampled audio is linear16 mono @ stt_sample_rate as Deepgram expects.
            resampled = resample_pcm(frame, self.sample_rate, self.stt_sample_rate)
            if not resampled or len(resampled) == 0:
                continue
            # Optional throttle: log resampled size for first few frames.
            if _frames_logged <= 3:
                logger.debug(
                    "pipeline_resampled",
                    extra={
                        "src_bytes": len(frame),
                        "dst_bytes": len(resampled),
                        "src_rate": self.sample_rate,
                        "dst_rate": self.stt_sample_rate,
                    },
                )
            await self.stt.send_audio(resampled)

            # Silero VAD on 48k buffer for barge-in. Run in a worker thread
            # so the (CPU-heavy, ~10ms) torch inference never blocks the
            # event loop — blocking it would starve the outbound send loop and
            # make the played audio crackle.
            if self._vad_model is not None:
                self._vad_buffer.append(frame)
                self._vad_samples += len(frame) // 2
                if self._vad_samples >= VAD_MIN_SAMPLES_48K:
                    prob = await asyncio.to_thread(self._run_vad)
                    self.bargein.on_vad(prob)

    def _run_vad(self) -> float:
        import torch

        audio_int16 = np.concatenate(
            [np.frombuffer(b, dtype=np.int16) for b in self._vad_buffer]
        )
        audio_f32 = audio_int16.astype(np.float32) / 32768.0
        audio_tensor = torch.from_numpy(audio_f32)
        self._vad_buffer = []
        self._vad_samples = 0
        try:
            return float(self._vad_model(audio_tensor, self.sample_rate).item())
        except Exception:
            return 0.0

    # ── Worker 2: TTS synthesis ──

    @staticmethod
    def _should_flush(buf: str) -> bool:
        """Decide when a buffered reply chunk is ready to synthesize.

        Flush on a completed sentence (so TTS starts the moment a sentence is
        finished) once we have enough text to amortize TTS startup latency,
        or on a hard size cap so very long sentences still stream.
        """
        s = buf.strip()
        if len(s) < 15:
            return False
        if s[-1] in ".!?":
            return True
        if len(s) >= 120:
            return True
        return False

    async def _tts_synth_worker(self):
        # Watchdog: detect when audio is being sent but Deepgram produces
        # zero transcripts (half-open connection).
        first_audio_sent_at = None
        NO_TRANSCRIPT_WARN_S = 20.0

        while self._running:
            try:
                transcript = await self.stt.get_final_transcript(timeout=0.15)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # pragma: no cover
                inc_error("stt_read")
                logger.error(f"stt_read_error: {type(e).__name__}: {e}", extra={"error": str(e)})
                continue

            # Track when audio starts flowing to detect dead connections.
            last_audio_ts = getattr(self.stt, '_last_real_audio_ts', 0)
            if first_audio_sent_at is None and last_audio_ts > 0:
                first_audio_sent_at = last_audio_ts

            if not transcript:
                # Watchdog: if audio has been sent for >20s with zero transcripts,
                # Deepgram's connection is likely half-open — trigger reconnect.
                if (
                    first_audio_sent_at is not None
                    and self.stt.connected
                    and (time.monotonic() - first_audio_sent_at) > NO_TRANSCRIPT_WARN_S
                ):
                    logger.warning(
                        f"stt_no_transcripts: audio sent for {NO_TRANSCRIPT_WARN_S}s "
                        "with zero transcripts — triggering reconnect"
                    )
                    first_audio_sent_at = None  # reset, let reconnect happen
                    if hasattr(self.stt, '_connected'):
                        self.stt._connected = False
                continue

            # Got a transcript — reset watchdog.
            first_audio_sent_at = None

            # Barge-in may have already cancelled this turn.
            if self._tts_cancel.is_set():
                self._tts_cancel.clear()
                self.clear_output()
                continue

            # Route the user transcript through the agent. on_transcript is an
            # async generator that yields reply chunks as the LLM streams them.
            # We buffer chunks and synthesize each completed sentence as soon as
            # it's ready, so TTS starts overlapping the LLM generation (real-time
            # feel) instead of waiting for the full reply.
            if self.on_transcript is None:
                continue

            try:
                buf = ""
                tok_count = 0
                logger.debug(f"tts_worker: processing transcript: {transcript[:80]!r}")
                async for tok in self.on_transcript(transcript):
                    # Barge-in cancelled mid-generation -> drop the rest.
                    if self._tts_cancel.is_set():
                        self._tts_cancel.clear()
                        self.clear_output()
                        buf = ""
                        break
                    if not tok:
                        continue
                    tok_count += 1
                    buf += tok
                    if self._should_flush(buf):
                        logger.debug(f"tts_worker: flushing {len(buf)}-char turn ({tok_count} tokens)")
                        await self._synthesize_turn(buf.strip())
                        buf = ""
                logger.debug(f"tts_worker: generator done, {tok_count} tokens, buf={len(buf)} chars")
                if buf.strip():
                    await self._synthesize_turn(buf.strip())
            except Exception as e:
                inc_error("agent")
                logger.error(f"agent_processing_failed: {type(e).__name__}: {e}", extra={"error": str(e)})
                await self._synthesize_turn(
                    "Sorry, I ran into an error. Please try again."
                )

    async def _synthesize_turn(self, text: str):
        """Synthesize one transcript and stream chunks to the outbound queue."""
        logger.debug(f"tts_synth: start ({len(text)} chars): {text[:60]!r}...")
        self.bargein.set_agent_speaking(True)
        started = time.monotonic()
        first_chunk_at = None
        sent_any = False
        total_bytes = 0
        chunk_count = 0
        try:
            async for chunk in self._tts_stream(text):
                # Barge-in: abort if a cancellation arrived mid-generation.
                if self._tts_cancel.is_set():
                    self._tts_cancel.clear()
                    self.clear_output()
                    logger.info("tts_interrupted_by_bargein")
                    return
                if first_chunk_at is None:
                    first_chunk_at = time.monotonic()
                    record_tts_latency(first_chunk_at - started)
                try:
                    self._outbound.put_nowait(chunk)
                    sent_any = True
                    total_bytes += len(chunk)
                    chunk_count += 1
                except asyncio.QueueFull:
                    # Drop oldest to make room (keep latency low).
                    with contextlib.suppress(asyncio.QueueEmpty):
                        self._outbound.get_nowait()
                    try:
                        self._outbound.put_nowait(chunk)
                        total_bytes += len(chunk)
                        chunk_count += 1
                    except asyncio.QueueFull:
                        pass
        finally:
            self.bargein.set_agent_speaking(False)
            elapsed = time.monotonic() - started
            if sent_any and first_chunk_at is not None:
                record_pipeline_latency(time.monotonic() - started)
            logger.debug(
                f"tts_synth: done chunks={chunk_count} bytes={total_bytes} "
                f"sent={sent_any} elapsed={elapsed:.3f}s"
            )

    async def _tts_stream(self, text: str):
        """Yield raw int16 PCM @ sample_rate chunks for *text*.

        Uses Fish Audio streaming when configured, else falls back to the
        active backend's WAV synthesis decoded + resampled.
        """
        # Fish Audio streaming path.
        synth_stream = getattr(self.tts, "synthesize_stream_pcm", None)
        if synth_stream is not None:
            try:
                chunk_count = 0
                total_bytes = 0
                async for chunk in synth_stream(text, self.sample_rate):
                    chunk_count += 1
                    total_bytes += len(chunk)
                    yield chunk
                logger.debug(f"tts_stream: streaming path delivered {chunk_count} chunks ({total_bytes} bytes)")
                return
            except Exception as e:
                logger.warning("tts_streaming_failed", extra={"error": str(e), "action": "fallback"})

        # Fallback: full WAV from active backend -> resample to call rate.
        try:
            from .tts import _wav_to_pcm, _resample_pcm

            wav = await asyncio.to_thread(self.tts.synthesize_to_wav, text)
            if not wav:
                logger.warning("tts_stream: fallback WAV returned None/empty")
                return
            pcm, sr = _wav_to_pcm(wav)
            if sr != self.sample_rate:
                pcm = _resample_pcm(pcm, sr, self.sample_rate)
            logger.debug(f"tts_stream: fallback path delivered {len(pcm)} bytes")
            yield pcm
        except Exception as e:
            inc_error("tts_synth")
            logger.error(f"tts_fallback_failed: {type(e).__name__}: {e}", extra={"error": str(e)})

    # ── Worker 3: Barge-in monitor ──

    async def _bargein_monitor(self):
        while self._running:
            try:
                partial = await self.stt.get_partial_transcript(timeout=0.1)
            except asyncio.CancelledError:
                raise
            except Exception:
                continue

            if partial and self.bargein.agent_speaking:
                confirmed = self.bargein.on_partial(partial)
                if confirmed:
                    self._trigger_bargein()

            # Also re-check grace expiry: if VAD onset happened and grace passed
            # with a content word already seen, confirm now.
            if (
                self.bargein.agent_speaking
                and self.bargein._content_word_seen
                and self.bargein._grace_end_time
                and time.time() >= self.bargein._grace_end_time
            ):
                self._trigger_bargein()

    def _trigger_bargein(self):
        if self._bargein_event.is_set():
            return
        self._bargein_event.set()
        metrics = self.bargein.confirm_interrupt()
        # Signal the synth worker to stop producing more audio.
        self._tts_cancel.set()
        self.clear_output()
        logger.info("bargein_confirmed", extra=metrics)
        if self.on_bargein:
            try:
                self.on_bargein(metrics)
            except Exception as e:
                logger.warning("bargein_callback_error", extra={"error": str(e)})
        # Reset the event after a short window so repeated triggers are counted.
        asyncio.create_task(self._reset_bargein_event())

    async def _reset_bargein_event(self):
        await asyncio.sleep(0.3)
        self._bargein_event.clear()
