"""LiveKit VoIP Agent — Nally over a phone call via SIP Ingress.

Zero-cost phone interface: LiveKit Cloud (free tier) terminates the call via a
SIP Inbound Trunk, and this agent joins the room as a voice participant. A SIP
app like Linphone dials the trunk number and gets a real-time streaming
conversation with the same Nally brain used by web/Telegram/CLI.

Run:
    python -m nally.voice.livekit_agent

Pipeline:
    SIP audio -> silero VAD -> Deepgram streaming STT (batch stt.transcribe
    fallback) -> session_manager.process -> existing tts.synthesize_to_wav
    (Piper/ElevenLabs) -> room audio, with barge-in interruption.

Env:
    LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET  (LiveKit Cloud)
    DEEPGRAM_API_KEY        (optional — streaming STT)
    NALLY_VOIP_STREAMING_STT (default: on if DEEPGRAM_API_KEY is set)
    NALLY_VOIP_TTS          (optional — "plugin" uses livekit-plugins-elevenlabs;
                             default: existing Piper/ElevenLabs backend)
    ELEVENLABS_API_KEY      (optional — plugin TTS)
"""

import asyncio
import contextlib
import logging
import os
import threading
from typing import Optional

import numpy as np

from livekit import rtc
from livekit.agents import AgentServer, AutoSubscribe, JobContext, cli, vad
from livekit.plugins import silero

logger = logging.getLogger("nally.voice.livekit_agent")

OUTPUT_SAMPLE_RATE = 48000
OUTPUT_CHANNELS = 1
INPUT_SAMPLE_RATE = 16000
FRAME_DURATION = 0.02  # 20ms playback chunks so barge-in can cut promptly

server = AgentServer()


# ── Speech helpers ─────────────────────────────────────────


def _frames_to_float32(frames: list) -> bytes:
    """Concatenate rtc.AudioFrames into raw float32 mono PCM bytes."""
    parts = []
    for f in frames:
        arr = np.asarray(f.to_numpy(), dtype=np.float32)
        if arr.ndim > 1:
            arr = arr.mean(axis=1)
        parts.append(arr)
    if not parts:
        return b""
    return np.concatenate(parts).astype(np.float32).tobytes()


def _transcribe_batch(frames: list) -> str:
    """Batch STT via existing voice/stt.py (Groq -> faster-whisper)."""
    from ..voice import stt

    audio = _frames_to_float32(frames)
    if not audio:
        return ""
    return stt.transcribe(audio, sample_rate=INPUT_SAMPLE_RATE).strip()


def _wav_to_frames(wav_bytes: bytes, target_rate: int = OUTPUT_SAMPLE_RATE) -> list:
    """Parse a WAV file (int16 PCM) into a list of 20ms rtc.AudioFrames at 48kHz."""
    if len(wav_bytes) < 44:
        return []
    sample_rate = int.from_bytes(wav_bytes[24:28], "little")
    num_channels = int.from_bytes(wav_bytes[22:24], "little")
    bits = int.from_bytes(wav_bytes[34:36], "little")
    data = wav_bytes[44:]

    dtype = "int16" if bits == 16 else "int32"
    samples = np.frombuffer(data, dtype=dtype).astype(np.float32)
    if bits == 16:
        samples /= 32768.0
    else:
        samples /= 2147483648.0
    if num_channels > 1:
        samples = samples.reshape(-1, num_channels).mean(axis=1)

    if sample_rate != target_rate:
        n = int(round(len(samples) * target_rate / sample_rate))
        if len(samples) > 1:
            samples = np.interp(
                np.linspace(0, len(samples) - 1, n),
                np.arange(len(samples)),
                samples,
            )

    int16 = (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16)
    chunk = int(target_rate * FRAME_DURATION)
    frames = []
    for i in range(0, len(int16), chunk):
        seg = int16[i : i + chunk]
        frames.append(
            rtc.AudioFrame(
                data=seg.tobytes(),
                sample_rate=target_rate,
                num_channels=OUTPUT_CHANNELS,
                samples_per_channel=len(seg),
            )
        )
    return frames


def _classify_yes_no(text: str) -> bool:
    """Classify a short user utterance as an approval (yes/no)."""
    yes_words = {"yes", "yeah", "yep", "approve", "ok", "okay", "sure", "do it", "confirm", "go ahead"}
    no_words = {"no", "nope", "deny", "cancel", "stop", "nah", "negative"}
    words = set(text.lower().split())
    approved = bool(words & yes_words)
    denied = bool(words & no_words)
    if approved and not denied:
        return True
    if denied:
        return False
    return False


def _approval_prompt(data: dict) -> str:
    """Human-readable approval prompt for a pending tool call."""
    tool_name = data.get("name", "unknown")
    args = data.get("args", {})
    if tool_name == "run_command":
        return f"Approve running this command: {args.get('command', '?')}. Say yes to approve, or no to deny."
    if tool_name == "file_ops":
        return f"Approve {args.get('action', '')} file {args.get('file_path', '?')}. Say yes or no."
    return f"Approve {tool_name}? Say yes or no."


# ── Per-call handler ───────────────────────────────────────


class SipCall:
    """One in-progress phone call: listens, thinks via Nally, speaks, barge-in."""

    def __init__(self, ctx: JobContext, participant: rtc.RemoteParticipant, source: rtc.AudioSource):
        self._ctx = ctx
        self._participant = participant
        self._source = source
        # Unique per caller — one session each, so history/memory is per caller.
        self._session_id = f"voip:{participant.identity}"
        self._loop = asyncio.get_event_loop()
        self._pending_approval: Optional[dict] = None
        self._play_task: Optional[asyncio.Task] = None
        self._interrupted = False

        self._streaming_enabled = self._resolve_streaming_stt()
        self._tts_plugin = self._resolve_tts_plugin()

    # ── capability detection ──

    def _resolve_streaming_stt(self) -> bool:
        if os.getenv("NALLY_VOIP_STREAMING_STT", "").lower() == "false":
            return False
        return bool(os.getenv("DEEPGRAM_API_KEY"))

    def _resolve_tts_plugin(self):
        if os.getenv("NALLY_VOIP_TTS", "").lower() != "plugin":
            return None
        if not os.getenv("ELEVENLABS_API_KEY"):
            return None
        try:
            from livekit.plugins import elevenlabs

            return elevenlabs.ElevenLabs()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"ElevenLabs plugin unavailable, using existing TTS backend: {e}")
            return None

    # ── emit bridge (agent thread -> event loop) ──

    def _emit(self, event: str, data: dict):
        if event == "confirmation_required":
            self._pending_approval = data
            with contextlib.suppress(RuntimeError):
                asyncio.run_coroutine_threadsafe(
                    self._speak(_approval_prompt(data)), self._loop
                )

    # ── TTS / playback ──

    async def _speak(self, text: str):
        if not text or not text.strip():
            return
        await self._interrupt_tts()

        if self._tts_plugin is not None:
            try:
                frames = []
                async for f in self._tts_plugin.synthesize(text):
                    frames.append(f)
                if frames:
                    self._play_task = asyncio.create_task(self._play_frames(frames))
                    return
            except Exception as e:  # noqa: BLE001
                logger.warning(f"Plugin TTS failed, using existing backend: {e}")

        from ..voice import tts

        wav = await asyncio.to_thread(tts.synthesize_to_wav, text)
        if wav:
            self._play_task = asyncio.create_task(self._play_wav(wav))

    async def _play_wav(self, wav_bytes: bytes):
        await self._play_frames(_wav_to_frames(wav_bytes))

    async def _play_frames(self, frames: list):
        try:
            for frame in frames:
                if self._interrupted:
                    break
                self._source.capture_frame(frame)
                await asyncio.sleep(0.005)  # yield so VAD can set _interrupted
        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.error(f"Playback failed: {e}")

    async def _interrupt_tts(self):
        """Barge-in: stop whatever Nally is saying (called on user speech start)."""
        self._interrupted = True
        if self._play_task and not self._play_task.done():
            self._play_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._play_task
        self._source.clear_queue()
        self._play_task = None
        self._interrupted = False

    # ── STT ──

    async def _new_stt_stream(self):
        if not self._streaming_enabled:
            return None
        try:
            from livekit.plugins import deepgram

            return deepgram.STT().stream()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Streaming STT unavailable, using batch STT: {e}")
            return None

    @staticmethod
    async def _drain_stt(stt_stream) -> str:
        parts = []
        try:
            async for speech in stt_stream:
                if getattr(speech, "is_final", True) or speech.text:
                    parts.append(speech.text)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Streaming STT failed, using batch STT: {e}")
            return ""
        return " ".join(p for p in parts if p).strip()

    # ── turn loop ──

    async def _process_vad(self, vad_stream, audio_stream):
        speech_frames: list = []
        stt_stream = None

        async for event in vad_stream:
            event_type = event.type

            if event_type == vad.VADEventType.START_OF_SPEECH:
                speech_frames = []
                stt_stream = await self._new_stt_stream()
                await self._interrupt_tts()  # barge-in

            elif event_type == vad.VADEventType.INFERENCE_DONE:
                speech_frames.extend(event.frames)
                if stt_stream is not None:
                    for f in event.frames:
                        stt_stream.push_frame(f)

            elif event_type == vad.VADEventType.END_OF_SPEECH:
                speech_frames.extend(event.frames)

                if stt_stream is not None:
                    for f in event.frames:
                        stt_stream.push_frame(f)
                    await stt_stream.flush()
                    text = await self._drain_stt(stt_stream)
                    stt_stream = None
                else:
                    text = await asyncio.to_thread(_transcribe_batch, speech_frames)

                speech_frames = []
                if text:
                    await self._respond(text.strip())

    async def _respond(self, text: str):
        # If a tool approval is pending, the next utterance answers it.
        if self._pending_approval is not None:
            data = self._pending_approval
            self._pending_approval = None
            approved = _classify_yes_no(text)
            tc_id = data.get("tool_call_id", "")

            async def _resolve():
                from ..agent.graph import resolve_approval

                resolve_approval(tc_id, approved)

            await asyncio.to_thread(_resolve)
            await self._speak("Approved." if approved else "Denied.")
            return

        def _process():
            from ..agent.sessions import session_manager

            return session_manager.process(self._session_id, text, emit=self._emit)

        try:
            response = await asyncio.to_thread(_process)
        except Exception as e:  # noqa: BLE001
            logger.error(f"Agent failed for {self._session_id}: {e}")
            response = "Sorry, I ran into an error. Please try again."

        if not response or not response.strip():
            await self._speak("Sorry, I didn't catch that. Please try again.")
            return

        from ..voice.formatter import format_for_voice

        await self._speak(format_for_voice(response))

    # ── entrypoint driver ──

    async def run(self):
        audio_stream = rtc.AudioStream.from_participant(
            self._participant, track_source=rtc.TrackSource.SOURCE_MICROPHONE
        )
        vad_stream = silero.VAD.load(min_speech_duration=0.2, min_silence_duration=0.6).stream()

        # Greeting (non-interruptible so the caller hears it fully).
        await self._speak("Hi, this is Nally. I'm here. Go ahead.")

        async def _feed_audio():
            async for ev in audio_stream:
                vad_stream.push_frame(ev.frame)

        try:
            await asyncio.gather(_feed_audio(), self._process_vad(vad_stream, audio_stream))
        finally:
            await self._interrupt_tts()
            with contextlib.suppress(Exception):
                await audio_stream.aclose()


@server.rtc_session(agent_name="nally-voip")
async def entrypoint(ctx: JobContext):
    """Join the SIP room as the Nally voice participant."""
    logger.info(f"Connecting to room {ctx.room.name}")
    await ctx.connect(auto_subscribe=AutoSubscribe.AUDIO_ONLY)

    participant = await ctx.wait_for_participant()
    logger.info(f"SIP call from {participant.identity}")

    source = rtc.AudioSource(sample_rate=OUTPUT_SAMPLE_RATE, num_channels=OUTPUT_CHANNELS)
    track = rtc.LocalAudioTrack.create_audio_track("nally", source)
    await ctx.room.local_participant.publish_track(
        track,
        rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE),
    )

    call = SipCall(ctx, participant, source)
    try:
        await call.run()
    finally:
        logger.info(f"Call ended for {participant.identity}")
        ctx.shutdown()


if __name__ == "__main__":
    cli.run_app(server)
