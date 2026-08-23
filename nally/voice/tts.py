"""Text-to-speech with swappable backends.

Piper (default): local, free, no API key.
ElevenLabs: premium cloud TTS, requires API key.

Backend is selected via NALLY_TTS_BACKEND env var.
Public API: speak(text), synthesize_to_wav(text)
"""

import inspect
import io
import logging
import struct
import time
import typing
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

    async def synthesize_stream_pcm(self, text: str, target_sample_rate: int = 48000):
        """Stream synthesized audio via ElevenLabs WebSocket (raw protocol).

        Yields raw int16 PCM chunks at *target_sample_rate*. Uses the
        WebSocket input-streaming endpoint so audio starts arriving within
        ~300ms (Eleven Flash v2.5 TTFA). Falls back to HTTP on failure.
        """
        import asyncio
        import base64
        import json

        api_key, voice_id, model = self._get_config()
        # pcm_44100 requires Pro tier — use pcm_22050 which is available on all tiers.
        eleven_sr = 22050  # 22050 Hz is supported on all tiers (including Starter/Free)

        uri = (
            f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input"
            f"?model_id={model}&output_format=pcm_{eleven_sr}"
        )

        try:
            import websockets
            # Check if websockets.connect supports the 'proxy' parameter (added in v14)
            proxy_supported = "proxy" in inspect.signature(websockets.connect).parameters
        except Exception:
            proxy_supported = False

        try:
            t_conn = time.monotonic()
            async with websockets.connect(
                uri,
                additional_headers={"xi-api-key": api_key},
                open_timeout=30,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=5,
                **({"proxy": None} if proxy_supported else {}),
            ) as ws:
                logger.debug(f"el_ws: connected in {time.monotonic() - t_conn:.1f}s")

                # 1. Send voice settings (init frame)
                init_msg = json.dumps({
                    "text": " ",
                    "voice_settings": {
                        "stability": 0.65,
                        "similarity_boost": 0.80,
                        "style": 0.35,
                        "use_speaker_boost": True,
                    },
                })
                await ws.send(init_msg)
                await asyncio.sleep(0)  # yield to event loop — flush transport write buffer
                logger.debug("el_ws: sent_init")

                # 2. Send the full text
                await ws.send(json.dumps({"text": text}))
                await asyncio.sleep(0)
                logger.debug("el_ws: sent_text")

                # 3. Flush (signal end of input)
                await ws.send(json.dumps({"text": "", "flush": True}))
                await asyncio.sleep(0)
                logger.debug("el_ws: sent_flush")

                # 4. Receive audio chunks and stream-resample to target rate.
                #    Maintain an input accumulator so inter-chunk phase is
                #    continuous — we only yield once we have a full 20ms output
                #    chunk and keep leftover input samples for the next cycle.
                input_acc = np.array([], dtype=np.int16)
                out_chunk = int(target_sample_rate * 0.02)  # 960 samples @48k — exact 20ms, do not drift
                ratio = eleven_sr / target_sample_rate       # ~0.459
                # Exact input needed for one output chunk: 960 * 22050/48000 = 441
                needed_in = int(round(out_chunk * eleven_sr / target_sample_rate))  # 441 @22050→48000
                msg_count = 0
                audio_bytes_in = 0
                chunks_out = 0
                first_audio_at = None
                last_data_at = time.monotonic()

                # Fast failure: if no audio chunk arrives within 5s of
                # connecting, the WS is likely half-open — abort immediately
                # instead of waiting 20s for the server-side timeout.
                WS_AUDIO_TIMEOUT = 5.0
                # If no data arrives for this long after first audio, consider
                # the stream complete (server may not send isFinal for short text).
                WS_SILENCE_TIMEOUT = 3.0

                while True:
                    # Timeout check: no new data for WS_SILENCE_TIMEOUT after first audio
                    if first_audio_at is not None:
                        remaining = WS_SILENCE_TIMEOUT - (time.monotonic() - last_data_at)
                        if remaining <= 0:
                            logger.debug(
                                f"el_ws: silence after audio — stream complete "
                                f"(msgs={msg_count} chunks_out={chunks_out})"
                            )
                            break
                        recv_timeout = max(remaining, 0.5)
                    else:
                        # No audio yet: use fast-failure timeout
                        recv_timeout = WS_AUDIO_TIMEOUT - (time.monotonic() - t_conn)
                        if recv_timeout <= 0:
                            logger.warning(
                                f"el_ws: no audio received within {WS_AUDIO_TIMEOUT}s — "
                                "aborting (likely half-open connection)"
                            )
                            break

                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=recv_timeout)
                    except asyncio.TimeoutError:
                        if first_audio_at is None:
                            # Still no audio — fast failure
                            logger.warning(
                                f"el_ws: no audio received within {WS_AUDIO_TIMEOUT}s — "
                                "aborting (likely half-open connection)"
                            )
                            break
                        # Got audio earlier but silence now — stream done
                        logger.debug(
                            f"el_ws: recv timeout after audio — stream complete "
                            f"(msgs={msg_count} chunks_out={chunks_out})"
                        )
                        break

                    last_data_at = time.monotonic()
                    if isinstance(msg, bytes):
                        continue
                    data = json.loads(msg)
                    msg_count += 1
                    audio_b64 = data.get("audio", "")
                    if audio_b64:
                        if first_audio_at is None:
                            first_audio_at = time.monotonic()
                            logger.debug(f"el_ws: first_audio in {first_audio_at - t_conn:.1f}s")
                        chunk_pcm = np.frombuffer(
                            base64.b64decode(audio_b64), dtype=np.int16
                        )
                        input_acc = np.append(input_acc, chunk_pcm)
                        audio_bytes_in += len(chunk_pcm) * 2

                    # Emit as many 20ms output chunks as we can — use
                    # high-quality resampler (soxr/scipy) not linear interp.
                    # Each 20ms @48k = 960 samples needs ~442 @22050; we slice
                    # exactly needed_in and resample to out_chunk for phase-continuous
                    # output, then emit strictly 960-sample frames.
                    while len(input_acc) >= needed_in:
                        window = input_acc[:needed_in]
                        # Use shared helper for quality: soxr > scipy > linear
                        resampled_bytes = _resample_pcm(
                            window.tobytes(), eleven_sr, target_sample_rate
                        )
                        # _resample_pcm may be slightly off due to filter delay; force 960
                        resampled = np.frombuffer(resampled_bytes, dtype=np.int16)
                        if len(resampled) != out_chunk:
                            if len(resampled) > out_chunk:
                                resampled = resampled[:out_chunk]
                            else:
                                resampled = np.pad(
                                    resampled, (0, out_chunk - len(resampled))
                                )
                        yield resampled.tobytes()
                        chunks_out += 1
                        input_acc = input_acc[needed_in:]

                    if data.get("isFinal"):
                        break

                logger.debug(
                    f"el_ws: done msgs={msg_count} audio_in={audio_bytes_in} "
                    f"chunks_out={chunks_out} tail={len(input_acc)}"
                )

                # Flush any remaining input samples (< 20ms tail) — resample once
                # to keep total duration exact (avoids fast/slow drift).
                if len(input_acc) > 0:
                    tail_bytes = _resample_pcm(
                        input_acc.tobytes(), eleven_sr, target_sample_rate
                    )
                    if tail_bytes:
                        yield tail_bytes

        except Exception as e:
            logger.warning(f"ElevenLabs WS streaming failed ({type(e).__name__}: {e}); fallback to HTTP")
            # Fallback: full HTTP synthesis -> decode -> resample
            wav = await asyncio.to_thread(self.synthesize_to_wav, text)
            if wav:
                pcm, sr = _wav_to_pcm(wav)
                if sr != target_sample_rate:
                    pcm = _resample_pcm(pcm, sr, target_sample_rate)
                chunk_samples = int(target_sample_rate * 0.02)
                step = chunk_samples * 2
                for i in range(0, len(pcm), step):
                    yield pcm[i : i + step]

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


class FishAudioBackend(TTSBackend):
    """Fish Audio cloud TTS — premium quality, ultra-low latency, requires API key."""

    name = "fishaudio"

    def _get_config(self):
        from ..config import FISH_API_KEY, FISH_VOICE_ID, FISH_MODEL
        if not FISH_API_KEY:
            raise ValueError("FISH_API_KEY not set")
        return FISH_API_KEY, FISH_VOICE_ID, FISH_MODEL

    def speak(self, text: str) -> None:
        if not text or not text.strip():
            return
        try:
            import sounddevice as sd
            import io, wave
            wav_bytes = self.synthesize_to_wav(text)
            if not wav_bytes:
                print(f"[TTS unavailable] {text}")
                return
            with wave.open(io.BytesIO(wav_bytes), 'rb') as w:
                sample_rate = w.getframerate()
                frames = w.readframes(w.getnframes())
                audio_int16 = np.frombuffer(frames, dtype=np.int16)
                audio_f32 = audio_int16.astype(np.float32) / 32768.0
                sd.play(audio_f32, samplerate=sample_rate)
                sd.wait()
            logger.debug(f"Fish Audio spoke: {text[:100]}")
        except Exception as e:
            logger.error(f"Fish Audio TTS failed: {e}")
            print(f"[TTS unavailable] {text}")

    def synthesize_to_wav(self, text: str) -> bytes | None:
        if not text or not text.strip():
            return None
        try:
            import asyncio
            # Run async function in a sync environment
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None

            if loop and loop.is_running():
                # We are in an running loop, run in executor
                return asyncio.run_coroutine_threadsafe(self.async_synthesize(text), loop).result()
            else:
                return asyncio.run(self.async_synthesize(text))
        except Exception as e:
            logger.error(f"Fish Audio sync wrapper synthesis failed: {e}")
            return None

    async def async_synthesize(self, text: str) -> bytes | None:
        """Asynchronously synthesize text using fishaudio SDK."""
        try:
            from fishaudio import AsyncFishAudio
            api_key, voice_id, model = self._get_config()
            async with AsyncFishAudio(api_key=api_key) as client:
                # convert returns wav/mp3 bytes. We ask for WAV for compatibility.
                # _fish_convert retries without the voice id if it is rejected.
                audio_bytes = await _fish_convert(
                    client, text=text, model=model, voice_id=voice_id, fmt="wav"
                )
                if audio_bytes:
                    return audio_bytes
                raise RuntimeError("Fish Audio returned empty audio")
        except Exception as e:
            logger.error(f"Fish Audio async synthesis failed: {e}")
            # Graceful fallback to local Piper so calls still get audio.
            pcm = _piper_pcm(text, 48000)
            if pcm is not None:
                logger.warning("Falling back to Piper TTS for async_synthesize")
                return _build_wav(pcm, 48000)
            return None

    async def synthesize_stream_pcm(self, text: str, target_sample_rate: int = 48000):
        """Stream synthesized audio as raw int16 PCM chunks at *target_sample_rate*.

        Yields successive chunks of raw PCM (int16, mono) ready for playback.
        Uses Fish Audio's streaming endpoint when available, falling back to a
        single convert() call that is decoded + resampled.
        """
        import asyncio

        from fishaudio import AsyncFishAudio
        from fishaudio.types.tts import TTSConfig

        api_key, voice_id, model = self._get_config()

        async def _stream():
            async with AsyncFishAudio(api_key=api_key) as client:
                try:
                    # Preferred: true streaming PCM. Fish Audio PCM streaming only
                    # supports 8000/16000/24000/32000/44100 — never 4800/48000 —
                    # so we stream at the highest supported rate and resample to
                    # the call rate afterwards.
                    fish_sr = 44100
                    stream_kwargs = {
                        "text": text,
                        "format": "pcm",
                        "model": model,
                        "config": TTSConfig(sample_rate=fish_sr),
                    }
                    if voice_id:
                        stream_kwargs["reference_id"] = voice_id
                    stream_iter = await client.tts.stream(**stream_kwargs)
                    raw = b""
                    async for chunk in stream_iter:
                        if chunk:
                            raw += chunk
                    if not raw:
                        return
                    pcm = _resample_pcm(raw, fish_sr, target_sample_rate)
                    # Emit 20ms chunks (1920 bytes mono / 3840 stereo @48k).
                    # Larger than the binding's 10ms example batch, but it
                    # plays at the correct rate and lets the outbound loop
                    # sustain realtime with far less per-frame send overhead
                    # (fewer send_frame calls), eliminating choppy playback.
                    chunk_samples = int(target_sample_rate * 0.02)
                    step = chunk_samples * 2
                    for i in range(0, len(pcm), step):
                        yield pcm[i : i + step]
                    return
                except Exception as e:  # pragma: no cover - network/SDK edge cases
                    logger.debug(f"Fish stream PCM failed ({e}); falling back to convert")

                # Fallback 1: full synthesis -> WAV -> decode -> resample.
                wav = await _fish_convert(
                    client, text=text, model=model, voice_id=voice_id, fmt="wav"
                )
                if wav:
                    pcm, sr = _wav_to_pcm(wav)
                    if sr != target_sample_rate:
                        pcm = _resample_pcm(pcm, sr, target_sample_rate)
                    # Emit in ~40ms chunks (matches silence frames).
                    chunk_samples = int(target_sample_rate * 0.04)
                    step = chunk_samples * 2
                    for i in range(0, len(pcm), step):
                        yield pcm[i : i + step]
                    return

                # Fallback 2: local Piper (no cloud dependency).
                logger.warning(
                    "Fish Audio streaming unavailable — falling back to Piper TTS"
                )
                pcm = _piper_pcm(text, target_sample_rate)
                if pcm:
                    chunk_samples = int(target_sample_rate * 0.2)
                    step = chunk_samples * 2
                    for i in range(0, len(pcm), step):
                        yield pcm[i : i + step]

        async for chunk in _stream():
            yield chunk


# ── Helpers ───────────────────────────────────────────────


def _wav_to_pcm(wav_bytes: bytes) -> tuple[bytes, int]:
    """Decode a WAV (or RIFF) buffer into raw int16 PCM and its sample rate."""
    import wave

    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        sample_rate = w.getframerate()
        frames = w.readframes(w.getnframes())
    return frames, sample_rate


def _resample_pcm(pcm_int16: bytes, src_rate: int, dst_rate: int) -> bytes:
    """Resample raw int16 mono PCM from src_rate to dst_rate.

    Free-tier ElevenLabs only offers pcm_22050 (or mp3), so 22050→48000 is the
    hot path.  Linear ``np.interp`` is hoarse and changes duration — use a
    proper polyphase resampler.

    Priority:
      1. soxr (best quality, light) — ``pip install soxr``
      2. scipy.signal.resample_poly (good, already in many envs)
      3. linear interp fallback (kept for minimal envs)
    """
    if src_rate == dst_rate or not pcm_int16:
        return pcm_int16
    # Fast path for empty / single sample
    audio_len = len(pcm_int16) // 2
    if audio_len < 2:
        return pcm_int16
    # Try soxr first (HQ)
    try:
        import soxr  # type: ignore

        # soxr expects float32 in [-1, 1]
        audio_f32 = np.frombuffer(pcm_int16, dtype=np.int16).astype(np.float32) / 32768.0
        # soxr.resample(x, in_rate, out_rate, quality='HQ')
        out_f32 = soxr.resample(audio_f32, src_rate, dst_rate, quality="HQ")
        out_f32 = np.clip(out_f32, -1.0, 1.0)
        return (out_f32 * 32767).astype(np.int16).tobytes()
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"soxr resample failed ({e}), trying scipy")
    # Try scipy polyphase
    try:
        from scipy.signal import resample_poly  # type: ignore
        import math

        audio = np.frombuffer(pcm_int16, dtype=np.int16).astype(np.float32)
        g = math.gcd(int(src_rate), int(dst_rate))
        up = int(dst_rate // g)
        down = int(src_rate // g)
        # Kaiser window 5.0 is a good tradeoff for speech
        resampled = resample_poly(audio, up, down, window=("kaiser", 5.0))
        # resample_poly can produce slightly longer/shorter due to filter delay;
        # trim/pad to exact expected length for deterministic chunking downstream.
        expected = int(round(len(audio) * dst_rate / src_rate))
        if len(resampled) > expected:
            resampled = resampled[:expected]
        elif len(resampled) < expected:
            resampled = np.pad(resampled, (0, expected - len(resampled)))
        return np.clip(resampled, -32768, 32767).astype(np.int16).tobytes()
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"scipy resample failed ({e}), falling back to linear")
    # Fallback: linear interp (original, hoarse but functional)
    audio = np.frombuffer(pcm_int16, dtype=np.int16).astype(np.float32)
    n_dst = int(round(len(audio) * dst_rate / src_rate))
    if n_dst <= 0:
        return b""
    resampled = np.interp(
        np.linspace(0, len(audio) - 1, n_dst), np.arange(len(audio)), audio
    )
    return np.clip(resampled, -32768, 32767).astype(np.int16).tobytes()


def _piper_pcm(text: str, target_sample_rate: int) -> bytes | None:
    """Synthesize text to raw int16 PCM via the local Piper backend.

    Used as a graceful fallback when a cloud TTS backend (Fish/ElevenLabs)
    is unavailable (network error, billing/quota, bad key). Returns None if
    Piper itself cannot synthesize.
    """
    try:
        wav = PiperBackend().synthesize_to_wav(text)
        if not wav:
            return None
        pcm, sr = _wav_to_pcm(wav)
        if sr != target_sample_rate:
            pcm = _resample_pcm(pcm, sr, target_sample_rate)
        return pcm
    except Exception as e:  # pragma: no cover - environment dependent
        logger.error(f"Piper fallback synthesis failed: {e}")
        return None


async def _fish_convert(client, *, text: str, model: str, voice_id: str | None, fmt: str):
    """Call Fish convert(), retrying once without a reference_id if the
    supplied voice is rejected (e.g. 'Reference not found')."""
    candidates = [voice_id, None] if voice_id else [None]
    last_err = None
    for vid in candidates:
        try:
            kwargs = {"text": text, "model": model, "format": fmt}
            if vid:
                kwargs["reference_id"] = vid
            return await client.tts.convert(**kwargs)
        except Exception as e:
            if vid and "reference" in str(e).lower():
                logger.warning(f"Fish voice '{vid}' rejected; using model default voice")
                last_err = e
                continue
            raise
    raise last_err


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
    import subprocess
    import tempfile

    from ..utils import ffmpeg_available

    if not ffmpeg_available():
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
    import subprocess
    import tempfile

    from ..utils import ffmpeg_available

    if not ffmpeg_available():
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
    elif TTS_BACKEND == "fishaudio":
        try:
            from ..config import FISH_API_KEY

            if not FISH_API_KEY:
                logger.warning("FISH_API_KEY not set — falling back to Piper")
                _active_backend = PiperBackend()
            else:
                _active_backend = FishAudioBackend()
                logger.info("Using Fish Audio TTS backend")
        except Exception as e:
            logger.warning(f"Fish Audio init failed ({e}) — falling back to Piper")
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
