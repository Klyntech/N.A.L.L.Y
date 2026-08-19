"""Telegram Voice Calls — standalone runner.

Launches pytgcalls with Telethon backend, auto-answers incoming calls,
and routes audio through the Nally voice pipeline.

Run:
    python run_tg_call.py

Env: NALLY_VOICE_CALLS_ENABLED=true, TELEGRAM_USER_* credentials
"""
import asyncio
import contextlib
import logging
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from nally.tools import load_all_tools
load_all_tools()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("run_tg_call")


async def main():
    from nally.config import (
        TELEGRAM_USER_API_ID,
        TELEGRAM_USER_API_HASH,
        TELEGRAM_USER_PHONE,
        TELEGRAM_USER_ID,
        NALLY_VOICE_CALLS_ENABLED,
    )

    if not NALLY_VOICE_CALLS_ENABLED:
        logger.error("NALLY_VOICE_CALLS_ENABLED is not set to true. Exiting.")
        return

    if not TELEGRAM_USER_API_ID or not TELEGRAM_USER_API_HASH:
        logger.error("TELEGRAM_USER_API_ID / TELEGRAM_USER_API_HASH not configured.")
        return

    # ── Observability (OpenTelemetry / Prometheus / OTLP) ──
    from nally.config import OTEL_METRICS_PORT, OTEL_EXPORTER_OTLP_ENDPOINT
    from nally.voice.metrics import init_telemetry

    init_telemetry(
        service_name="nally-voice-call",
        metrics_port=OTEL_METRICS_PORT,
        otlp_endpoint=OTEL_EXPORTER_OTLP_ENDPOINT or None,
    )

    # ── Telethon client (SEPARATE session from user.py to avoid SQLite lock) ──
    from telethon import TelegramClient, events
    from nally.telegram.user import SESSION_DIR

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    session_path = SESSION_DIR / "nally_call"

    telethon_client = TelegramClient(
        str(session_path),
        TELEGRAM_USER_API_ID,
        TELEGRAM_USER_API_HASH,
    )

    logger.info("telethon_connecting")
    await telethon_client.start(phone=TELEGRAM_USER_PHONE)
    me = await telethon_client.get_me()
    logger.info("telethon_connected", extra={"first_name": me.first_name, "username": me.username})

    # ── pytgcalls client ──
    try:
        from pytgcalls import PyTgCalls
        from pytgcalls.types import (
            MediaStream,
            ExternalMedia,
            StreamFrames,
            StreamEnded,
            ChatUpdate,
            Direction,
            Device,
            RecordStream,
        )
        from pytgcalls.types.raw import AudioParameters
    except ImportError:
        logger.error(
            "py-tgcalls not installed. Run: pip install 'py-tgcalls[telethon]'"
        )
        return

    tg_call = PyTgCalls(telethon_client)
    await tg_call.start()
    logger.info("pytgcalls_started")

    # ── Pre-warm greeting cache (zero-latency on call start) ──
    from nally.telegram.voice_call import _greeting_cache
    logger.info("warming_greeting_cache")
    await _greeting_cache.warm()

    # ── Pre-warm STT + TTS WebSocket connections (avoid handshake delay during call) ──
    from nally.config import DEEPGRAM_API_KEY, ELEVENLABS_API_KEY
    async def _warm_connections():
        # Deepgram — open WebSocket now so it's ready when call arrives
        if DEEPGRAM_API_KEY:
            try:
                from nally.voice.stt import DeepgramStreamingSTT
                stt = DeepgramStreamingSTT(DEEPGRAM_API_KEY)
                ok = await stt.connect()
                if ok:
                    logger.info("deepgram_prewarmed")
                    # Keep connection alive with a keepalive, then close
                    # (the actual call will create its own connection)
                    await stt.close()
                else:
                    logger.warning("deepgram_prewarm_failed")
            except Exception as e:
                logger.warning("deepgram_prewarm_error", extra={"error": str(e)})

        # ElevenLabs — test WebSocket connectivity
        if ELEVENLABS_API_KEY:
            try:
                import websockets
                import json as _json
                from nally.config import ELEVENLABS_VOICE_ID, ELEVENLABS_MODEL
                voice_id = ELEVENLABS_VOICE_ID or "Jkfq779A6b949pWiEfQv"
                uri = f"wss://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream-input?model_id={ELEVENLABS_MODEL}&output_format=pcm_44100"
                async with websockets.connect(
                    uri,
                    additional_headers={"xi-api-key": ELEVENLABS_API_KEY},
                    open_timeout=5,
                    close_timeout=3,
                ) as ws:
                    await ws.send(_json.dumps({"text": " ", "voice_settings": {"stability": 0.65, "similarity_boost": 0.80}}))
                    logger.info("elevenlabs_prewarmed")
            except Exception as e:
                logger.warning("elevenlabs_prewarm_error", extra={"error": str(e)})

    await _warm_connections()

    # ── Active call sessions ──
    from nally.telegram.voice_call import VoiceCallSession

    active_sessions: dict[int, VoiceCallSession] = {}
    call_locks: dict[int, asyncio.Lock] = {}

    async def _join_call_media(chat_id: int):
        """Start external audio output AND enable inbound frame capture.

        pytgcalls only delivers StreamFrames (incoming remote audio) after
        record() is called — play() alone sets up the outgoing capture source
        but does NOT observe the incoming playback stream.
        """
        await tg_call.play(chat_id, MediaStream(ExternalMedia.AUDIO))
        await tg_call.record(
            chat_id,
            RecordStream(
                audio=True,
                audio_parameters=AudioParameters(bitrate=48000, channels=2),
            ),
        )
        logger.info("call_media_joined", extra={"call_id": chat_id})

    async def _answer_call(chat_id: int):
        """Answer an incoming call and start the voice loop."""
        if chat_id in active_sessions:
            logger.debug(f"Already in call with {chat_id}")
            return

        lock = call_locks.setdefault(chat_id, asyncio.Lock())
        if lock.locked():
            return

        async with lock:
            logger.info("answering_call", extra={"call_id": chat_id})

            session = VoiceCallSession(chat_id, tg_call=tg_call, use_pipeline=True)
            active_sessions[chat_id] = session

            try:
                # External audio mode so send_frame() (Nally's TTS) is actually
                # routed to the call output, and inbound StreamFrames flow.
                await _join_call_media(chat_id)
                await session.run()
            except Exception as e:
                logger.error(f"call_session_error: {type(e).__name__}: {e}", extra={"call_id": chat_id, "error": str(e)})
            finally:
                active_sessions.pop(chat_id, None)
                call_locks.pop(chat_id, None)
                with contextlib.suppress(Exception):
                    await tg_call.leave_call(chat_id)
                logger.info("call_ended", extra={"call_id": chat_id})

    async def _initiate_call(chat_id: int):
        """Initiate an outgoing call to the owner."""
        if chat_id in active_sessions:
            return

        session = VoiceCallSession(chat_id, tg_call=tg_call, use_pipeline=True)
        active_sessions[chat_id] = session

        try:
            await _join_call_media(chat_id)
            await session.run()
        except Exception as e:
                logger.error(f"outgoing_call_error: {type(e).__name__}: {e}", extra={"call_id": chat_id, "error": str(e)})
        finally:
            active_sessions.pop(chat_id, None)
            with contextlib.suppress(Exception):
                await tg_call.leave_call(chat_id)
            logger.info("call_ended", extra={"call_id": chat_id})

    # ── Handle pytgcalls updates (call state + audio frames) ──

    _first_frame_logged = [False]

    @tg_call.on_update()
    async def on_update(client, update):
        """Route pytgcalls updates to active sessions."""
        try:
            chat_id = update.chat_id

            # Find session with flexible ID resolution
            session = active_sessions.get(chat_id)
            if not session:
                alt_ids = [
                    abs(chat_id),
                    int(str(chat_id).replace("-100", "")),
                    int(f"-100{abs(chat_id)}")
                ]
                for alt_id in alt_ids:
                    if alt_id in active_sessions:
                        session = active_sessions[alt_id]
                        break

            if isinstance(update, StreamFrames):
                if not _first_frame_logged[0]:
                    _first_frame_logged[0] = True
                    logger.info("first_stream_frame", extra={
                        "call_id": chat_id,
                        "direction": str(update.direction),
                        "device": str(update.device),
                        "has_session": session is not None,
                    })

                # Only feed INCOMING (remote user) audio into STT. Our own TTS
                # is OUTGOING and must never be transcribed (feedback loop).
                # feed_frame() downmixes stereo->mono for the pipeline.
                if update.direction == Direction.INCOMING and update.device in (
                    Device.MICROPHONE,
                    Device.SPEAKER,
                ):
                    if session:
                        for frame in update.frames:
                            session.feed_frame(frame.frame)
                return

            if isinstance(update, StreamEnded):
                if session:
                    session.stop()
                return

            if isinstance(update, ChatUpdate):
                if update.status & ChatUpdate.Status.INCOMING_CALL:
                    logger.info("incoming_call", extra={"call_id": chat_id})
                    asyncio.create_task(_answer_call(chat_id))
                elif update.status & ChatUpdate.Status.DISCARDED_CALL:
                    logger.info("call_discarded", extra={"call_id": chat_id})
                    if session:
                        session.stop()
                elif update.status & ChatUpdate.Status.LEFT_CALL:
                    if session:
                        session.stop()
                return

            logger.debug(f"Call update from {chat_id}: {type(update).__name__}")
        except Exception as e:
            logger.error(f"update_handler_error: {type(e).__name__}: {e}", extra={"error": str(e)})

    # ── Handle "call me" DM command ──

    @telethon_client.on(events.NewMessage(pattern=r"(?i)^call me$"))
    async def on_call_me(event):
        """Initiate a call when owner sends 'call me'."""
        sender = await event.get_sender()
        if sender and sender.id != TELEGRAM_USER_ID:
            return

        chat_id = sender.id
        if chat_id in active_sessions:
            await event.reply("Already in a call with you.")
            return

        await event.reply("Calling you now...")
        asyncio.create_task(_initiate_call(chat_id))

    # ── Shutdown ──
    shutdown_event = asyncio.Event()

    def _signal_handler():
        logger.info("shutdown_signal_received")
        shutdown_event.set()

    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass  # Windows

    logger.info("voice_call_handler_ready")
    await shutdown_event.wait()

    # Cleanup
    for session in active_sessions.values():
        session.stop()
    active_sessions.clear()
    await tg_call.stop()
    await telethon_client.disconnect()
    logger.info("voice_call_handler_stopped")


if __name__ == "__main__":
    asyncio.run(main())
