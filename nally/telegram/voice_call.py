"""Telegram Voice Calls — real-time voice via group voice chats.

Pipeline: user speaks -> StreamFrames -> VoicePipeline (Deepgram STT + Silero
VAD + Fish Audio TTS + BargeInDetector) -> send_frame(MICROPHONE).

Requires: pytgcalls[telethon], silero-vad, torch, deepgram-sdk, fish-audio-sdk
Env: NALLY_VOICE_CALLS_ENABLED=true, TELEGRAM_USER_* credentials,
     DEEPGRAM_API_KEY, FISH_API_KEY (for streaming TTS)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Optional

import numpy as np

from ..config import (
    BARGEIN_GRACE_MS,
    DATA_DIR,
    DEEPGRAM_API_KEY,
)
from ..utils.logger import logger

# Telegram API imports for group voice chats
from telethon.tl.functions.channels import CreateChannelRequest
from telethon.tl.functions.messages import ExportChatInviteRequest, AddChatUserRequest

# Audio constants — Telegram calls use 48kHz mono
CALL_SAMPLE_RATE = 48000
STT_SAMPLE_RATE = 16000


# ── Pre-generated greeting cache (zero-latency on call start) ────────

class GreetingCache:
    """Cache 3 time-based greetings as raw PCM bytes.

    Greetings are pre-generated via ElevenLabs HTTP at startup so the first
    thing the user hears on a call has 0ms TTS latency. The cache is a
    process-lifetime singleton.
    """

    _GREETINGS = {
        "morning": "Good morning! This is Nally. How can I help you today?",
        "afternoon": "Hey, this is Nally. What's going on?",
        "evening": "Hey! Nally here. What's up?",
    }

    def __init__(self):
        self._cache: dict[str, bytes] = {}  # period -> raw PCM int16 mono @48k

    async def warm(self):
        """Generate all 3 greetings at startup. Best-effort, non-blocking."""
        import asyncio
        import struct
        import io

        from ..voice.tts import get_backend

        backend = get_backend()
        for period, text in self._GREETINGS.items():
            try:
                wav = await asyncio.to_thread(backend.synthesize_to_wav, text)
                if not wav:
                    logger.warning("greeting_tts_empty", extra={"period": period})
                    continue
                # Decode WAV to raw PCM int16 mono
                with wave.open(io.BytesIO(wav), "rb") as w:
                    sr = w.getframerate()
                    pcm = w.readframes(w.getnframes())
                # Resample to 48k if needed
                if sr != CALL_SAMPLE_RATE:
                    from ..voice.tts import _resample_pcm
                    pcm = _resample_pcm(pcm, sr, CALL_SAMPLE_RATE)
                # Normalize to -3dB peak for consistent loudness
                pcm_arr = np.frombuffer(pcm, dtype=np.int16)
                peak = np.max(np.abs(pcm_arr))
                if peak > 0:
                    target_peak = int(32767 * 0.707)  # -3dB
                    scale = target_peak / peak
                    pcm_arr = np.clip(pcm_arr.astype(np.float32) * scale, -32768, 32767).astype(np.int16)
                    pcm = pcm_arr.tobytes()
                self._cache[period] = pcm
                logger.info("greeting_ready", extra={"period": period, "bytes": len(pcm)})
            except Exception as e:
                logger.warning("greeting_failed", extra={"period": period, "error": str(e)})

    def get(self) -> bytes | None:
        """Return cached PCM for the current time of day, or None."""
        from datetime import datetime
        hour = datetime.now().hour
        if 5 <= hour < 12:
            period = "morning"
        elif 12 <= hour < 18:
            period = "afternoon"
        else:
            period = "evening"
        return self._cache.get(period)


# Process-lifetime singleton
import wave
_greeting_cache = GreetingCache()


# Group voice chat state
_voice_chat_group_id: Optional[int] = None
_voice_chat_invite_link: Optional[str] = None

# Silent audio used to establish the outbound stream (pytgcalls requires a path).
SILENT_PATH = str(DATA_DIR / "silent.wav")


def ensure_silent_wav():
    """Create a 1-second silent WAV if missing (used to open the call stream)."""
    import wave

    path = Path(SILENT_PATH)
    if path.exists():
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "w") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(CALL_SAMPLE_RATE)
        w.writeframes(b"\x00\x00" * CALL_SAMPLE_RATE)  # 1s of silence


def _classify_yes_no(text: str) -> bool:
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
    tool_name = data.get("name", "unknown")
    args = data.get("args", {})
    if tool_name == "run_command":
        return f"Approve running this command: {args.get('command', '?')}. Say yes to approve, or no to deny."
    if tool_name == "file_ops":
        return f"Approve {args.get('action', '')} file {args.get('file_path', '?')}. Say yes or no."
    return f"Approve {tool_name}? Say yes or no."


# ── Group voice chat management ────────────────────────────


async def ensure_voice_chat_group(client) -> tuple[int, str]:
    """Ensure a supergroup exists for voice chats. Returns (group_id, invite_link)."""
    global _voice_chat_group_id, _voice_chat_invite_link

    if _voice_chat_group_id:
        return _voice_chat_group_id, _voice_chat_invite_link

    state_file = DATA_DIR / "voice_chat_group.json"
    if state_file.exists():
        state = json.loads(state_file.read_text())
        _voice_chat_group_id = state["group_id"]
        _voice_chat_invite_link = state.get("invite_link")
        logger.info(f"Using existing voice chat group: {_voice_chat_group_id}")
        return _voice_chat_group_id, _voice_chat_invite_link

    logger.info("Creating voice chat supergroup...")
    result = await client(CreateChannelRequest(
        title="Nally Voice",
        about="Nally AI voice chat session",
        megagroup=True,
    ))

    group = result.chats[0]
    _voice_chat_group_id = group.id

    try:
        invite_result = await client(ExportChatInviteRequest(peer=_voice_chat_group_id, expire_seconds=3600))
        _voice_chat_invite_link = invite_result.link
    except Exception:
        _voice_chat_invite_link = None

    state_file.write_text(json.dumps({
        "group_id": _voice_chat_group_id,
        "invite_link": _voice_chat_invite_link,
    }))

    logger.info(f"Created voice chat group: {_voice_chat_group_id}")
    return _voice_chat_group_id, _voice_chat_invite_link


async def ensure_private_voice_group(client, user_id: int) -> tuple[int, str]:
    """Ensure a private supergroup for a specific user (1:1 call isolation).

    Beta: each 1:1 call gets its own private group so two simultaneous 1:1
    calls don't hear each other. State per user in voice_chat_group_{user_id}.json
    """
    state_file = DATA_DIR / f"voice_chat_group_{user_id}.json"
    if state_file.exists():
        try:
            state = json.loads(state_file.read_text())
            gid = state["group_id"]
            link = state.get("invite_link")
            logger.info(f"Using existing private voice group for {user_id}: {gid}")
            return gid, link
        except Exception:
            pass

    # Create new private supergroup for this user
    logger.info(f"Creating private voice group for user {user_id}...")
    result = await client(
        CreateChannelRequest(
            title=f"Nally Voice {user_id}",
            about=f"Private voice chat for user {user_id} — Nally beta 1:1",
            megagroup=True,
        )
    )
    group = result.chats[0]
    gid = group.id
    try:
        invite_result = await client(ExportChatInviteRequest(peer=gid, expire_seconds=86400))
        link = invite_result.link
    except Exception:
        link = None

    state_file.write_text(json.dumps({"group_id": gid, "invite_link": link}))
    logger.info(f"Created private voice group for {user_id}: {gid}")
    return gid, link


async def start_group_voice_chat(tg_call, client, group_id: int):
    """Start a voice chat in the group and join it."""
    from pytgcalls.types import MediaStream, GroupCallConfig

    call_id = group_id
    if not str(group_id).startswith("-"):
        call_id = int(f"-100{group_id}")

    logger.info(f"Starting voice chat in group {group_id} (pytgcalls ID: {call_id})")

    from telethon.tl.functions.phone import CreateGroupCallRequest
    try:
        # Telethon's rnd_id is not a public method; use random int
        import random

        rnd = getattr(client, "rnd_id", None)
        if callable(rnd):
            random_id = rnd()
        else:
            # Fallback: random 32-bit id
            random_id = random.randint(0, 0x7FFFFFFF)
        await client(CreateGroupCallRequest(peer=group_id, random_id=random_id))
        await asyncio.sleep(1.5)
    except Exception as e:
        logger.debug(f"Group call creation: {e} (might already exist)")

    ensure_silent_wav()
    await tg_call.play(call_id, MediaStream(SILENT_PATH), GroupCallConfig(auto_start=True))
    await asyncio.sleep(2.5)
    await tg_call.record(call_id)
    await asyncio.sleep(1.5)
    logger.info(f"Joined voice chat in group {call_id}")


async def leave_group_voice_chat(tg_call, group_id: int):
    """Leave the group voice chat."""
    call_id = group_id
    if not str(group_id).startswith("-"):
        call_id = int(f"-100{group_id}")
    try:
        await tg_call.leave_call(call_id)
        logger.info(f"Left voice chat in group {call_id}")
    except Exception as e:
        logger.error(f"Failed to leave voice chat: {e}")


# ── Per-session handler ───────────────────────────────────


class VoiceCallSession:
    """Voice call session driven by the overlapped VoicePipeline.

    Inbound frames are fed to the pipeline; outbound synthesized frames are
    pulled and sent via pytgcalls send_frame(MICROPHONE).
    """

    def __init__(self, chat_id: int, tg_call=None, use_pipeline: bool = True):
        self._chat_id = chat_id
        # Identity, not channel: calls share the owner's brain session with
        # text/web; only the route key stays call-specific.
        from ..agent.identity import resolve_session

        ref = resolve_session("tg_voice", chat_id=chat_id)
        self._session_id = ref.session_id
        self._route_key = ref.route_key
        self._tg_call = tg_call
        self._loop = asyncio.get_event_loop()
        self._pending_approval: Optional[dict] = None
        self._active = False
        self._use_pipeline = use_pipeline
        self._pipeline = None
        self._started_at = time.monotonic()

        # pytgcalls uses the raw chat_id for both play() and send_frame():
        # the user id for 1:1 calls, or the -100... supergroup id for group
        # calls. The caller is responsible for passing the correct id, so we
        # keep it as-is (no -100 mangling).
        self._caller_id = chat_id
        # Self-contained conversational history for the voice session so the
        # LLM has context across turns without touching the text-agent brain.
        self._voice_history: list[dict] = []
        self._heartbeat_task: asyncio.Task | None = None
        # Early-frame buffer: frames arriving before Deepgram pipeline is ready
        # are queued here (max ~1s) and flushed right after the pipeline
        # connects, so the first user utterance isn't lost and Deepgram gets
        # binary audio within 1-2s of opening the socket (avoids NET-0001).
        self._pending_frames: list[bytes] = []
        self._pending_frames_max = 50  # ~1s at 20ms frames

    # ── emit bridge (agent thread → event loop) ──

    def _emit(self, event: str, data: dict):
        if event == "confirmation_required":
            self._pending_approval = data
            with contextlib.suppress(RuntimeError):
                asyncio.run_coroutine_threadsafe(
                    self._speak(_approval_prompt(data)), self._loop
                )

    # ── Build pipeline ──

    def _build_pipeline(self):
        from ..voice import stt as stt_mod
        from ..voice import tts as tts_mod
        from ..voice.pipeline import VoicePipeline
        from ..voice.bargein import BargeInDetector

        deepgram_stt = stt_mod.DeepgramStreamingSTT(DEEPGRAM_API_KEY)
        tts_backend = tts_mod.get_backend()
        bargein = BargeInDetector(grace_ms=BARGEIN_GRACE_MS)
        return VoicePipeline(
            stt=deepgram_stt,
            tts=tts_backend,
            bargein=bargein,
            sample_rate=CALL_SAMPLE_RATE,
            stt_sample_rate=STT_SAMPLE_RATE,
            on_transcript=self._stream_transcript,
            on_bargein=self._on_bargein,
        )

    # ── Transport (pytgcalls send_frame) ──

    @staticmethod
    def _mono_to_stereo(data: bytes) -> bytes:
        """Telegram calls expect 48kHz STEREO signed-16 PCM (AudioQuality.HIGH).

        Our pipeline produces mono, so duplicate the single channel into L/R.
        """
        pcm = np.frombuffer(data, dtype=np.int16)
        stereo = np.empty(len(pcm) * 2, dtype=np.int16)
        stereo[0::2] = pcm
        stereo[1::2] = pcm
        return stereo.tobytes()

    async def _send_frame(self, data: bytes):
        """Send raw int16 PCM to the call via pytgcalls send_frame."""
        if not self._tg_call:
            return
        try:
            from pytgcalls.types.stream.device import Device
            from pytgcalls.types.stream.frame import Frame

            # pytgcalls calls are stereo; our pipeline is mono → upmix to stereo.
            payload = self._mono_to_stereo(data)
            await self._tg_call.send_frame(
                self._caller_id, Device.MICROPHONE, payload, Frame.Info()
            )
        except Exception as e:
            err_str = str(e).lower()
            if "not in a call" in err_str or "notincallerror" in err_str:
                self._active = False
                logger.info("call_not_active", extra={"call_id": self._caller_id})
            else:
                logger.warning("send_frame_failed", extra={"call_id": self._caller_id, "frame_bytes": len(data), "error": str(e)})

    # ── Agent bridge ──

    VOICE_SYSTEM_PROMPT = (
        "You are Nally, a concise voice assistant. Reply like you're speaking, "
        "not writing: 1-3 short sentences unless asked to elaborate. No "
        "markdown, no numbered lists, no long explanations. Keep it natural "
        "and conversational for someone listening on a call."
    )

    async def _stream_transcript(self, text: str):
        """Stream the agent reply token-by-token so TTS can begin immediately.

        Yields text chunks as the LLM produces them. The pipeline buffers these
        into sentences and starts synthesizing/speaking each sentence as soon
        as it's complete — overlapping generation with playback so the call
        feels real-time instead of waiting for the full round-trip.
        """
        logger.info("user_said", extra={"call_id": self._chat_id, "text": text[:100]})

        if self._pending_approval is not None:
            data = self._pending_approval
            self._pending_approval = None
            approved = _classify_yes_no(text)
            tc_id = data.get("tool_call_id", "")

            def _resolve():
                from ..agent.graph import resolve_approval

                resolve_approval(tc_id, approved)

            await asyncio.to_thread(_resolve)
            yield "Approved." if approved else "Denied."
            return

        from datetime import datetime, timezone

        now = datetime.now(timezone.utc)
        ts = (
            f"[Current time: {now.strftime('%Y-%m-%d %H:%M UTC')} | "
            f"Day: {now.strftime('%A')}]\n\n"
        )
        messages = [{"role": "system", "content": self.VOICE_SYSTEM_PROMPT}]
        messages += list(self._voice_history[-8:])
        messages.append({"role": "user", "content": ts + text})

        # Fast path: stream the LLM reply and yield tokens as they arrive.
        fast_path_yielded = False
        try:
            from ..agent.llm import NallyLLM

            llm = NallyLLM()
            gen = llm.stream_chat(messages)
            loop = asyncio.get_running_loop()
            q: asyncio.Queue = asyncio.Queue()

            def _pump():
                try:
                    for tok in gen:
                        loop.call_soon_threadsafe(q.put_nowait, tok)
                except Exception as e:  # pragma: no cover
                    logger.warning("voice_stream_pump_error", extra={"error": str(e)})
                finally:
                    loop.call_soon_threadsafe(q.put_nowait, None)

            threading.Thread(target=_pump, daemon=True).start()

            full: list[str] = []
            tok_count = 0
            while True:
                tok = await q.get()
                if tok is None:
                    break
                full.append(tok)
                tok_count += 1
                fast_path_yielded = True
                yield tok
            reply = "".join(full).strip()
            logger.info(f"voice_stream: fast path done, {tok_count} tokens, {len(reply)} chars")
            if reply:
                self._voice_history.append({"role": "user", "content": text})
                self._voice_history.append({"role": "assistant", "content": reply})
                # Mandatory persist: commit the turn into the shared brain so
                # text/web/Telethon see this call in history. Latency-critical
                # streaming already finished — the commit runs off-loop.
                try:
                    await asyncio.to_thread(self._commit_turn, text, reply)
                except Exception as e:
                    logger.warning("voice_commit_turn_failed", extra={"error": str(e)})
                return
        except Exception as e:
            # If the fast path already yielded partial tokens, don't also
            # yield the full fallback response — that would cause stuttered
            # audio (truncated LLM output + duplicate full reply).
            if fast_path_yielded:
                return
            logger.warning("voice_streaming_llm_failed", extra={"error": str(e)})

        # Fallback: full agent brain (slower, but correct for complex requests).
        try:
            from ..agent.sessions import session_manager

            response = await asyncio.to_thread(
                session_manager.process, self._session_id, text, self._emit
            )
            response = (response or "").strip()
            if response:
                yield response
        except Exception as e:
            logger.error(f"agent_failed: {type(e).__name__}: {e}", extra={"session_id": self._session_id, "error": str(e)})
            yield "Sorry, I ran into an error. Please try again."

    # ── Shared-brain persistence ──

    def _commit_turn(self, user_text: str, reply: str):
        """Commit a fast-path turn into the shared session brain (blocking)."""
        from ..agent.sessions import session_manager

        session_manager.commit_turn(self._session_id, user_text, reply)

    def _seed_history_from_brain(self):
        """Seed the short prompt window from shared history so a call picks
        up where text/web left off. Runs once, best-effort."""
        if self._voice_history:
            return
        try:
            from ..agent.sessions import session_manager

            hist = session_manager.get_history(self._session_id)
            msgs = [m for m in hist if m.get("role") in ("user", "assistant")][-8:]
            self._voice_history.extend(msgs)
            if msgs:
                logger.info(
                    "voice_history_seeded",
                    extra={"call_id": self._chat_id, "turns": len(msgs)},
                )
        except Exception as e:
            logger.debug(f"voice history seed failed: {type(e).__name__}: {e}")

    def _write_call_episode(self):
        """Best-effort light episode at hangup: 1-3 sentences on topics and
        decisions from the call — long-term recall, not a transcript copy.

        Skipped for short calls (<30s) or pure greeting/chitchat. Never
        blocks stop(): runs in a daemon thread and swallows all errors.
        """
        try:
            elapsed = time.monotonic() - getattr(self, "_started_at", time.monotonic())
            user_turns = [
                m for m in self._voice_history if m.get("role") == "user"
            ]
            substance = sum(len(m.get("content", "")) for m in user_turns)
            if elapsed < 30 or not user_turns or substance < 120:
                return

            transcript = "\n".join(
                f"{'User' if m.get('role') == 'user' else 'Nally'}: {m.get('content', '')}"
                for m in self._voice_history[-12:]
            )

            def _write():
                try:
                    from ..agent.llm import llm
                    from ..memory import memory_store

                    summary = llm.simple_chat(
                        user_message=(
                            "Summarize this voice call in 1-3 sentences: what was "
                            "discussed and any decisions or outcomes. Just the "
                            "summary, nothing else.\n\n" + transcript
                        ),
                        system_prompt=(
                            "You summarize voice calls tersely for long-term "
                            "memory. Output only the summary."
                        ),
                    )
                    summary = (summary or "").strip()
                    if summary:
                        memory_store.add_episode(
                            topic="Telegram voice call",
                            what_happened=summary,
                            tags=["voice-call"],
                        )
                        logger.info("call_episode_recorded", extra={"call_id": self._chat_id})
                except Exception as e:
                    logger.debug(f"call episode write failed: {type(e).__name__}: {e}")

            threading.Thread(target=_write, daemon=True).start()
        except Exception as e:
            logger.debug(f"call episode skipped: {type(e).__name__}: {e}")

    async def _process_transcript(self, text: str) -> str:
        """Run the user's transcript through the agent brain; return reply text."""
        logger.info("user_said", extra={"call_id": self._chat_id, "text": text[:100]})

        if self._pending_approval is not None:
            data = self._pending_approval
            self._pending_approval = None
            approved = _classify_yes_no(text)
            tc_id = data.get("tool_call_id", "")

            def _resolve():
                from ..agent.graph import resolve_approval

                resolve_approval(tc_id, approved)

            await asyncio.to_thread(_resolve)
            return "Approved." if approved else "Denied."

        def _process():
            from ..agent.sessions import session_manager

            return session_manager.process(self._session_id, text, emit=self._emit)

        try:
            response = await asyncio.to_thread(_process)
        except Exception as e:
            logger.error(f"agent_failed: {type(e).__name__}: {e}", extra={"session_id": self._session_id, "error": str(e)})
            response = "Sorry, I ran into an error. Please try again."

        if not response or not response.strip():
            return "Sorry, I didn't catch that. Please try again."

        from ..voice.formatter import format_for_voice

        return format_for_voice(response)

    async def _speak(self, text: str):
        """Synthesize and stream *text* to the caller (via pipeline or fallback)."""
        if not text or not text.strip():
            return
        if self._pipeline is not None:
            await self._pipeline.speak(text)
        else:
            # Legacy fallback (no pipeline): file-based playback.
            await self._speak_legacy(text)

    async def _speak_legacy(self, text: str):
        from ..voice import tts as tts_mod

        wav = await asyncio.to_thread(tts_mod.synthesize_to_wav, text)
        if not wav:
            return
        import tempfile

        tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False, dir=str(DATA_DIR / "voice_tmp"))
        tmp.write(wav)
        tmp.flush()
        tmp.close()
        if self._tg_call:
            from pytgcalls.types import MediaStream

            await self._tg_call.play(self._caller_id, MediaStream(tmp.name))
            await asyncio.sleep(1.0)

    def _on_bargein(self, metrics: dict):
        """Stop current playback immediately when a barge-in is confirmed."""
        logger.info("bargein_cutting_playback", extra={"latency_ms": metrics.get("latency_ms")})
        # Send a brief silence frame to halt the audio device output.
        silence = b"\x00\x00" * (CALL_SAMPLE_RATE // 50)  # 20ms silence @48k
        asyncio.run_coroutine_threadsafe(self._send_frame(silence), self._loop)

    # ── frame feeding ──

    @staticmethod
    def _stereo_to_mono(data: bytes) -> bytes:
        """Telegram calls are stereo 48k; the pipeline/STT expect mono 48k.

        Average L/R to mono. If the frame is already mono-packed (both halves
        equal) the average is a no-op, so this is safe either way.
        """
        if not data:
            return data
        pcm = np.frombuffer(data, dtype=np.int16)
        if len(pcm) % 2 != 0:
            pcm = pcm[:-1]
        left = pcm[0::2].astype(np.int32)
        right = pcm[1::2].astype(np.int32)
        mono = ((left + right) // 2).astype(np.int16)
        return mono.tobytes()

    def feed_frame(self, frame_bytes: bytes):
        """Feed an incoming audio frame into the pipeline (non-blocking).

        Frames arriving before the pipeline/Deepgram is ready are buffered
        (max ~1s) and flushed once the pipeline connects, so the first
        utterance isn't lost and Deepgram receives binary audio within 1-2s
        (avoids the NET-0001 idle timeout).
        """
        if not frame_bytes or len(frame_bytes) == 0:
            return
        # Inbound Telegram frames are stereo; the STT/VAD pipeline wants mono.
        mono = self._stereo_to_mono(frame_bytes)
        if not mono or len(mono) == 0:
            return
        # If pipeline is ready and STT is connected (or reconnecting, where
        # pipeline queues frames), forward immediately.
        if (
            self._pipeline is not None
            and self._pipeline.running
            and (self._pipeline.stt.connected or getattr(self._pipeline.stt, "_reconnecting", False))
        ):
            self._pipeline.feed_audio(mono)
            # Also flush any pending frames that arrived early (should be empty now).
            if self._pending_frames:
                for pending in self._pending_frames:
                    self._pipeline.feed_audio(pending)
                self._pending_frames.clear()
        else:
            # Buffer early frames until pipeline is ready (avoid NET-0001 + lost speech).
            if len(self._pending_frames) < self._pending_frames_max:
                self._pending_frames.append(mono)
            # If pipeline exists but isn't yet connected, still try to queue
            # (pipeline.feed_audio handles disconnect buffering).
            elif self._pipeline is not None and self._pipeline.running:
                self._pipeline.feed_audio(mono)

    # ── Main loop ──

    async def run(self):
        """Main voice chat loop: pipeline-driven streaming with barge-in."""
        self._active = True
        self._heartbeat_task = None

        # Pull recent shared-brain history into the short prompt window so
        # the call continues the cross-platform conversation (best-effort,
        # off-loop).
        try:
            await asyncio.to_thread(self._seed_history_from_brain)
        except Exception:
            pass

        # 2. Start pipeline BEFORE greeting so Deepgram warms while greeting
        # plays.  This ensures the first user utterance isn't lost and the
        # Deepgram socket gets binary audio within 1-2s (avoids NET-0001).
        # The pipeline is started in background so greeting has zero-latency.
        if self._use_pipeline:
            from ..voice.pipeline import VoicePipeline  # noqa: F401

            self._pipeline = self._build_pipeline()
            asyncio.create_task(self._start_pipeline_bg())

        # 1. Send greeting IMMEDIATELY via _send_frame (no pipeline needed)
        cached = _greeting_cache.get()
        if cached:
            logger.info("greeting_playing", extra={"call_id": self._chat_id, "bytes": len(cached)})
            chunk_step = int(CALL_SAMPLE_RATE * 0.02) * 2  # 20ms mono
            for i in range(0, len(cached), chunk_step):
                if not self._active:
                    break
                await self._send_frame(cached[i:i + chunk_step])
        else:
            # Generate a short synthetic tone as fallback greeting.
            # Must use _send_frame (not tg_call.play) to preserve
            # ExternalMedia.AUDIO mode for the outbound pipeline.
            duration_s = 0.5
            n_samples = int(CALL_SAMPLE_RATE * duration_s)
            t = np.linspace(0, duration_s, n_samples, dtype=np.float32)
            tone = (np.sin(2 * np.pi * 440 * t) * 16000).astype(np.int16)
            chunk_step = int(CALL_SAMPLE_RATE * 0.02)  # 20ms mono
            for i in range(0, len(tone), chunk_step):
                if not self._active:
                    break
                await self._send_frame(tone[i:i + chunk_step].tobytes())

        # 3. Start heartbeat (2s interval) — replaces all per-frame diagnostics
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        logger.info("voice_call_loop_started", extra={"call_id": self._chat_id})
        # pytgcalls external audio plays raw PCM at 48k; we emit 20ms frames
        # (3840 bytes stereo) so the outbound loop sustains realtime with
        # minimal per-frame send overhead. Silence is 20ms of mono int16 PCM.
        silence_frame = b"\x00\x00" * (CALL_SAMPLE_RATE // 50)  # 20ms silence
        secs_per_byte = 1.0 / (CALL_SAMPLE_RATE * 2)

        # Pace with a small *lead buffer*: keep the stream ~LEAD seconds ahead
        # of real-time so NTgCalls' jitter buffer always has data. Sending at
        # exactly 1x real-time with zero headroom lets any event-loop jitter
        # (Deepgram recv / keepalive share this loop) cause underrun clicks,
        # so we deliberately keep a little headroom and clamp the max lead to
        # avoid overflowing the binding's buffer.
        LEAD = 0.09       # target buffered lead (s)
        MAX_LEAD = 0.25   # never buffer more than this (avoid overflow)
        deadline = time.monotonic() + LEAD  # virtual playout clock
        secs_per_byte = 1.0 / (CALL_SAMPLE_RATE * 2)
        while self._active:
            frame = self._pipeline.get_output_frame() if self._pipeline else None
            if not frame:
                frame = silence_frame

            await self._send_frame(frame)

            frame_dur = len(frame) * secs_per_byte
            deadline += frame_dur
            now = time.monotonic()
            wait = deadline - now
            if wait < 0:
                # Behind real-time (slow send / event-loop contention). Send the
                # next frame immediately and KEEP the backlog in `deadline` so we
                # burst to refill the lead buffer — resetting to now would idle
                # the stream and cause underrun crackle. We never drop audio.
                wait = 0.0
            elif wait > MAX_LEAD:
                # Got too far ahead (e.g. after a greeting burst) -> clamp.
                deadline = now + MAX_LEAD
                wait = MAX_LEAD
            if wait > 0:
                await asyncio.sleep(wait)

        logger.info("voice_call_loop_ended", extra={"call_id": self._caller_id})

    async def _start_pipeline_bg(self):
        """Start pipeline in background — logs state transitions only."""
        try:
            ok = await self._pipeline.start()
            if ok:
                # Flush any frames that arrived before the pipeline was ready
                # so Deepgram gets audio within 1-2s of connecting.
                pending = len(self._pending_frames)
                if pending:
                    for p in self._pending_frames:
                        self._pipeline.feed_audio(p)
                    self._pending_frames.clear()
                    logger.info("pipeline_pending_flushed", extra={"call_id": self._chat_id, "flushed": pending})
                logger.info("pipeline_started", extra={"call_id": self._chat_id, "pending_flushed": pending})
            else:
                logger.warning("pipeline_stt_failed", extra={"call_id": self._chat_id})
        except Exception as e:
            logger.error(f"pipeline_start_error: {type(e).__name__}: {e}", extra={"call_id": self._chat_id, "error": str(e)})

    async def _heartbeat_loop(self):
        """Periodic heartbeat: one INFO line every 2s summarizing call health."""
        import time
        t0 = time.monotonic()
        while self._active:
            await asyncio.sleep(2.0)
            elapsed = time.monotonic() - t0
            q_out = self._pipeline._outbound.qsize() if self._pipeline else 0
            q_in = self._pipeline._inbound.qsize() if self._pipeline else 0
            stt = "connected" if (self._pipeline and self._pipeline.stt and self._pipeline.stt.connected) else "down"
            logger.info(
                "heartbeat",
                extra={
                    "call_id": self._chat_id,
                    "elapsed_s": round(elapsed, 1),
                    "outbound_q": q_out,
                    "inbound_q": q_in,
                    "stt": stt,
                },
            )

    def stop(self):
        """Stop the call session and pipeline."""
        self._active = False
        self._pending_frames.clear()
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            self._heartbeat_task = None
        if self._pipeline is not None:
            with contextlib.suppress(Exception):
                asyncio.run_coroutine_threadsafe(self._pipeline.stop(), self._loop)
            self._pipeline = None
        # Light episode for long-term recall (best-effort, never blocks).
        self._write_call_episode()
