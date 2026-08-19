"""Speech-to-text.

- transcribe(): batch fallback chain (Groq API -> faster-whisper local).
  Used by CLI push-to-talk voice mode.
- DeepgramStreamingSTT: realtime streaming STT via Deepgram Flux (WebSocket),
  used by the overlapped VoicePipeline for Telegram voice calls.
"""

import asyncio
import contextlib
import io
import logging
import struct
import time

import numpy as np

from .metrics import record_stt_latency

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


# ════════════════════════════════════════════════════════════════
#  Deepgram Flux — realtime streaming STT
# ════════════════════════════════════════════════════════════════


class DeepgramStreamingSTT:
    """Streaming STT over Deepgram's realtime WebSocket (Flux / nova-2).

    Usage:
        stt = DeepgramStreamingSTT(api_key)
        await stt.connect()
        # in a loop: await stt.send_audio(frame_16k_pcm)
        #            text = await stt.get_final_transcript()  # blocking
        await stt.close()

    Interim transcripts are queued continuously; get_final_transcript() returns
    only speech-final utterances. Each final transcript records stt_latency.
    """

    def __init__(self, api_key: str, sample_rate: int = 16000, model: str = "nova-2"):
        self.api_key = api_key
        self.sample_rate = sample_rate
        self.model = model
        self._socket = None
        self._cm = None
        self._connected = False
        self._final_queue: asyncio.Queue[str] = asyncio.Queue()
        self._partial_queue: asyncio.Queue[str] = asyncio.Queue(maxsize=50)
        self._recv_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None
        self._last_audio_sent_ts = 0.0
        self._last_real_audio_ts = 0.0
        self._closing = False
        self._reconnecting = False
        self._last_connect_time = 0.0  # monotonic timestamp of last successful connect()
        self._consecutive_quick_fails = 0  # recv dies within QUICK_FAIL_THRESHOLD seconds

    async def connect(self) -> bool:
        """Open the Deepgram WebSocket. Returns True on success."""
        if not self.api_key:
            logger.warning("DEEPGRAM_API_KEY not set — streaming STT disabled")
            return False
        try:
            from deepgram import AsyncDeepgramClient
        except ImportError:
            logger.error("deepgram-sdk not installed — streaming STT unavailable")
            return False

        # Tear down any previous tasks before opening a fresh socket.
        await self._cancel_tasks()

        try:
            client = AsyncDeepgramClient(api_key=self.api_key)
            # connect() is an async context manager in deepgram-sdk >=7.
            self._cm = client.listen.v1.connect(
                model=self.model,
                language="en",
                encoding="linear16",
                sample_rate=self.sample_rate,
                interim_results=True,
                punctuate=True,
                smart_format=True,
                vad_events=True,
            )
            self._socket = await self._cm.__aenter__()
            self._connected = True
            self._last_connect_time = time.monotonic()
            self._consecutive_quick_fails = 0
            # Drive the recv loop to dispatch incoming messages.
            self._recv_task = asyncio.create_task(self._recv_loop())
            # Keepalive: send silence during gaps so Deepgram's idle-timeout
            # (1011 "did not receive audio") never fires while the user is silent.
            self._keepalive_task = asyncio.create_task(self._keepalive_loop())
            # Fire an immediate keepalive so the idle timer is reset right away,
            # before the keepalive loop task even gets scheduled (startup can
            # starve the event loop for several seconds).
            with contextlib.suppress(Exception):
                await self._socket.send_keep_alive()
            logger.info("deepgram_connected")
            return True
        except Exception as e:
            logger.error(f"deepgram_connect_failed: {type(e).__name__}: {e}", extra={"error": str(e)})
            self._connected = False
            return False

    async def _cancel_tasks(self):
        """Cancel the recv/keepalive tasks if still running."""
        self._connected = False
        for task in (self._recv_task, self._keepalive_task):
            if task is not None and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
        self._recv_task = None
        self._keepalive_task = None

    async def _ensure_connected(self) -> bool:
        """Reconnect if the socket has dropped (e.g. idle 1011)."""
        if self._connected:
            return True
        if self._closing:
            return False
        return await self.connect()

    QUICK_FAIL_THRESHOLD = 5.0  # recv dying within this many seconds = systematic issue

    async def _reconnect_loop(self):
        """Attempt to re-establish the socket after an unexpected drop.

        Uses exponential backoff when recv dies quickly after connecting
        (systematic issue vs transient network drop).
        """
        if self._reconnecting:
            return
        self._reconnecting = True
        try:
            # Detect quick fail: recv died within QUICK_FAIL_THRESHOLD of connect.
            time_since_connect = time.monotonic() - self._last_connect_time
            if time_since_connect < self.QUICK_FAIL_THRESHOLD and self._last_connect_time > 0:
                self._consecutive_quick_fails += 1
            else:
                self._consecutive_quick_fails = 0

            max_attempts = 10
            for attempt in range(1, max_attempts + 1):
                if self._closing or self._connected:
                    return

                # Backoff: base 3s, doubles with consecutive quick fails, capped at 30s.
                backoff = min(3 * (2 ** self._consecutive_quick_fails), 30)
                if attempt > 1:
                    logger.warning(
                        "deepgram_reconnect",
                        extra={
                            "attempt": attempt,
                            "max": max_attempts,
                            "backoff_s": round(backoff, 1),
                            "quick_fails": self._consecutive_quick_fails,
                        },
                    )
                    await asyncio.sleep(backoff)

                if self._closing or self._connected:
                    return
                logger.info(
                    "deepgram_reconnecting",
                    extra={"attempt": attempt, "quick_fails": self._consecutive_quick_fails},
                )
                if await self.connect():
                    logger.info("deepgram_reconnected")
                    return

            logger.error(
                f"deepgram_reconnect_failed: exhausted {max_attempts} attempts, "
                f"{self._consecutive_quick_fails} consecutive quick fails",
                extra={"attempts": max_attempts, "quick_fails": self._consecutive_quick_fails},
            )
        finally:
            self._reconnecting = False

    RECV_TIMEOUT = 15.0  # seconds — if no Deepgram message in this window, connection is dead

    async def _recv_loop(self):
        """Receive messages and dispatch final transcripts to the queue."""
        try:
            while self._socket is not None:
                try:
                    msg = await asyncio.wait_for(
                        self._socket.recv(), timeout=self.RECV_TIMEOUT
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        f"deepgram_recv_timeout: no data for {self.RECV_TIMEOUT}s, reconnecting"
                    )
                    break
                if msg is None:
                    break
                msg_type = getattr(msg, "type", None)
                if msg_type != "Results":
                    continue
                is_final = getattr(msg, "is_final", False) or getattr(
                    msg, "speech_final", False
                )
                channel = getattr(msg, "channel", None)
                if channel is None:
                    continue
                alts = getattr(channel, "alternatives", None) or []
                if not alts:
                    continue
                text = (getattr(alts[0], "transcript", "") or "").strip()
                if not text:
                    continue
                if is_final:
                    latency = 0.0
                    if self._last_audio_sent_ts:
                        latency = max(0.0, time.monotonic() - self._last_audio_sent_ts)
                    record_stt_latency(latency, {"model": self.model})
                    await self._final_queue.put(text)
                    self._last_audio_sent_ts = 0.0
                else:
                    # Interim result — feed barge-in / live UI (best-effort).
                    with contextlib.suppress(asyncio.QueueFull):
                        self._partial_queue.put_nowait(text)
        except asyncio.CancelledError:
            pass
        except Exception as e:
            err_info = f"{type(e).__name__}: {e}"
            logger.error(
                f"deepgram_recv_error: {err_info}",
                extra={
                    "error": err_info,
                    "socket": str(self._socket) if self._socket else "None",
                },
            )
        finally:
            self._connected = False
            if not self._closing:
                asyncio.create_task(self._reconnect_loop())

    async def _keepalive_loop(self):
        """Send keepalive pings to Deepgram during gaps to prevent idle timeout.

        Sends silence audio (via send_media) + text keepalive (via send_keep_alive)
        every 5s, but only AFTER real audio has been sent. Sending silence before
        any real audio can confuse Deepgram's audio pipeline.
        """
        silence_1s = b"\x00\x00" * self.sample_rate  # 1s of silence @16k
        try:
            while self._connected and self._socket is not None:
                now = time.monotonic()
                silence_needed = (
                    self._last_real_audio_ts > 0.0
                    and (now - self._last_real_audio_ts) > 3.0
                )
                if silence_needed:
                    try:
                        await self._socket.send_media(silence_1s)
                        await self._socket.send_keep_alive()
                    except Exception as e:
                        logger.warning(f"deepgram_keepalive_failed: {type(e).__name__}: {e}", extra={"error": str(e)})
                        break
                elif self._last_real_audio_ts == 0.0:
                    # No real audio yet — text-only keepalive to reset idle timer
                    with contextlib.suppress(Exception):
                        await self._socket.send_keep_alive()
                await asyncio.sleep(5.0)
        except asyncio.CancelledError:
            pass

    async def send_audio(self, audio_bytes: bytes):
        """Send a chunk of raw int16 PCM audio (at self.sample_rate)."""
        if self._socket is None or not self._connected:
            # Socket dropped (idle timeout). Reconnect lazily so a late
            # utterance is still captured instead of silently dropped.
            if not await self._ensure_connected():
                return
        if not self._last_audio_sent_ts:
            self._last_audio_sent_ts = time.monotonic()
        self._last_real_audio_ts = time.monotonic()
        try:
            await asyncio.wait_for(self._socket.send_media(audio_bytes), timeout=5.0)
        except asyncio.TimeoutError:
            logger.warning("deepgram_send_timeout: send blocked 5s, marking disconnected")
            self._connected = False
        except Exception as e:
            logger.warning(f"deepgram_send_failed: {type(e).__name__}: {e}", extra={"error": str(e)})
            self._connected = False

    async def get_final_transcript(self, timeout: float | None = None) -> str | None:
        """Return the next speech-final transcript, or None on timeout/close."""
        try:
            if timeout is None:
                return await self._final_queue.get()
            return await asyncio.wait_for(self._final_queue.get(), timeout)
        except asyncio.TimeoutError:
            return None

    async def get_partial_transcript(self, timeout: float = 0.05) -> str | None:
        """Return the latest interim transcript, or None if none available."""
        try:
            return await asyncio.wait_for(self._partial_queue.get(), timeout)
        except (asyncio.TimeoutError, asyncio.QueueEmpty):
            return None

    @property
    def connected(self) -> bool:
        return self._connected

    async def close(self):
        """Close the Deepgram connection and clean up."""
        self._closing = True
        self._connected = False
        if self._keepalive_task is not None:
            self._keepalive_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._keepalive_task
            self._keepalive_task = None
        if self._recv_task is not None:
            self._recv_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._recv_task
            self._recv_task = None
        if self._socket is not None:
            try:
                await self._socket.send_close_stream()
            except Exception:
                pass
        if self._cm is not None:
            with contextlib.suppress(Exception):
                await self._cm.__aexit__(None, None, None)
        self._socket = None
        self._cm = None
        self._connected = False
