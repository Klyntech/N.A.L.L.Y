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

        # Patch Deepgram SDK WebSocket connections to force proxy=None.
        # websockets >= 14 defaults proxy=True which probes Windows system proxy
        # settings and can create half-open connections.  deepgram-sdk 7.x
        # previously used install_transport(async_factory=...) but the SDK's
        # _AsyncTransportShim does `transport = factory()` without awaiting an
        # async factory, yielding a coroutine instead of a real websocket ->
        # `'coroutine' object has no attribute 'recv'` and `can't send non-None
        # value to a just-started coroutine`.  Patch websockets_client_connect
        # directly with an async context manager that disables the proxy.
        if not getattr(DeepgramStreamingSTT, "_transport_patched", False):
            try:
                import importlib
                import sys
                import websockets as _ws
                from contextlib import asynccontextmanager

                @asynccontextmanager
                async def _proxy_disabled_connect(url, extra_headers=None, additional_headers=None, **kwargs):
                    # SDK passes `extra_headers`, websockets expects `additional_headers`.
                    headers = extra_headers if extra_headers is not None else additional_headers
                    if headers is None:
                        headers = {}
                    # Merge any kwargs-passed headers.
                    if "extra_headers" in kwargs:
                        headers = kwargs.pop("extra_headers") or headers
                    # websockets.connect in v16 uses additional_headers + proxy param.
                    async with _ws.connect(
                        url,
                        additional_headers=headers,
                        proxy=None,
                        **kwargs,
                    ) as ws:
                        yield ws

                # Patch global websockets.connect to default proxy=None so any
                # direct usage (e.g. ElevenLabs prewarm) also avoids Windows proxy
                # probing that can create half-open connections.
                _orig_ws_connect = _ws.connect

                def _patched_ws_connect(uri, *args, **kwargs):
                    if "proxy" not in kwargs:
                        kwargs["proxy"] = None
                    if "extra_headers" in kwargs:
                        if "additional_headers" not in kwargs:
                            kwargs["additional_headers"] = kwargs.pop("extra_headers")
                        else:
                            kwargs.pop("extra_headers", None)
                    return _orig_ws_connect(uri, *args, **kwargs)

                _ws.connect = _patched_ws_connect  # type: ignore[assignment]
                # Also patch websockets.legacy.client.connect if present.
                try:
                    import websockets.legacy.client as _legacy_ws  # type: ignore

                    _orig_legacy = _legacy_ws.connect

                    def _patched_legacy(uri, *args, **kwargs):
                        if "proxy" not in kwargs:
                            kwargs["proxy"] = None
                        return _orig_legacy(uri, *args, **kwargs)

                    _legacy_ws.connect = _patched_legacy  # type: ignore[assignment]
                except Exception:
                    pass

                # Patch all 8 auto-generated Deepgram modules.
                _target_modules = [
                    "deepgram.listen.v1.raw_client",
                    "deepgram.listen.v1.client",
                    "deepgram.listen.v2.raw_client",
                    "deepgram.listen.v2.client",
                    "deepgram.speak.v1.raw_client",
                    "deepgram.speak.v1.client",
                    "deepgram.agent.v1.raw_client",
                    "deepgram.agent.v1.client",
                ]
                for mod_path in _target_modules:
                    mod = sys.modules.get(mod_path)
                    if mod is None:
                        try:
                            mod = importlib.import_module(mod_path)
                        except ImportError:
                            continue
                    if hasattr(mod, "websockets_client_connect"):
                        mod.websockets_client_connect = _proxy_disabled_connect
                    # Some modules also expose websockets_sync_client for sync path.
                    if hasattr(mod, "websockets_sync_client"):
                        # Sync shim not needed for async STT, but ensure proxy disabled there too.
                        try:
                            import websockets.sync.client as _sync_ws
                            _orig_sync = _sync_ws.connect

                            def _sync_no_proxy(url, additional_headers=None, **k):
                                k["proxy"] = None
                                return _orig_sync(url, additional_headers=additional_headers, **k)

                            # Best-effort: patch sync client if present.
                            pass
                        except Exception:
                            pass

                DeepgramStreamingSTT._transport_patched = True
                logger.info("deepgram_transport_proxy_disabled")
            except Exception as e:
                logger.warning(f"deepgram_transport_patch_failed: {type(e).__name__}: {e}")

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
            # Explicitly set channels=1 and match encoding/sample_rate to the
            # PCM we actually send (linear16 @ sample_rate).  Wrong values =
            # Deepgram treats data as invalid and eventually times out (NET-0001).
            self._cm = client.listen.v1.connect(
                model=self.model,
                language="en",
                encoding="linear16",
                sample_rate=self.sample_rate,
                channels=1,
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
            # Critical: Deepgram requires BINARY audio within ~10s.
            # Text KeepAlive alone does NOT prevent NET-0001 — we must send
            # real binary audio immediately.  Send 100ms of silence (1600
            # samples @16k = 3200 bytes) to satisfy the timer.
            # NOTE: Do NOT set _last_real_audio_ts here — that timestamp
            # tracks *user* audio for the pipeline's stt_no_transcripts
            # watchdog. Setting it here makes the watchdog think real audio
            # has been flowing for 20s, triggering a false reconnect.
            with contextlib.suppress(Exception):
                silence_100ms = b"\x00\x00" * (self.sample_rate // 10)  # 100ms @16k
                await self._socket.send_media(silence_100ms)
                self._last_audio_sent_ts = time.monotonic()
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

        Deepgram closes with 1011 if ~10s pass with no binary audio.  Text
        KeepAlive alone is NOT enough (NET-0001) — we must keep sending a
        little BINARY silence.  We send 100ms silence + KeepAlive every 3s
        whenever no real user audio has arrived for >2s, and a text keepalive
        otherwise.
        """
        silence_100ms = b"\x00\x00" * (self.sample_rate // 10)  # 100ms @16k = 3200 bytes
        _last_log = 0.0
        try:
            while self._connected and self._socket is not None:
                now = time.monotonic()
                silence_needed = (
                    self._last_real_audio_ts == 0.0
                    or (now - self._last_real_audio_ts) > 2.0
                )
                try:
                    if silence_needed:
                        await self._socket.send_media(silence_100ms)
                        await self._socket.send_keep_alive()
                    else:
                        await self._socket.send_keep_alive()
                    # Throttled diagnostic log (every 10s) so we can verify
                    # keepalive is actually firing during debugging.
                    if now - _last_log >= 10.0:
                        _last_log = now
                        since_real = round(now - self._last_real_audio_ts, 1) if self._last_real_audio_ts else "none"
                        logger.debug(
                            "deepgram_keepalive_sent",
                            extra={"silence_mode": silence_needed, "since_real_audio_s": since_real},
                        )
                except Exception as e:
                    logger.warning(f"deepgram_keepalive_failed: {type(e).__name__}: {e}", extra={"error": str(e)})
                    break
                await asyncio.sleep(3.0)
        except asyncio.CancelledError:
            pass

    async def send_audio(self, audio_bytes: bytes):
        """Send a chunk of raw int16 PCM audio (at self.sample_rate)."""
        # Clinton suggestion: never send empty bytes — Deepgram ignores them
        # and they don't reset the idle timer.
        if not audio_bytes or len(audio_bytes) == 0:
            return
        if self._socket is None or not self._connected:
            # Socket dropped (idle timeout). Reconnect lazily so a late
            # utterance is still captured instead of silently dropped.
            if not await self._ensure_connected():
                return
        if not self._last_audio_sent_ts:
            self._last_audio_sent_ts = time.monotonic()
        self._last_real_audio_ts = time.monotonic()
        # Log first few bytes of every non-silent chunk so we can confirm real
        # audio is arriving (as suggested in Clinton's debugging tip).
        # Only log at DEBUG to avoid spamming, but keep a throttled INFO for empty/silent.
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
