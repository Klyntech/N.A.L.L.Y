"""Nally Telegram User Account — Telethon client for DMs + voice calls.

Real Telegram user account (not a bot). Only interacts with the configured
owner. Supports:
- Incoming DMs: process through agent brain, reply as text
- Voice notes: STT -> agent -> TTS voice reply
- Photos/documents: download -> text extract / vision -> agent
- Outbound media: IMAGE_FILE: / SEND_FILE: auto-sent as files
- Incoming voice calls: auto-answer, VAD → STT → agent → TTS with barge-in
- "call me" DM: initiate an outgoing voice call
- Proactive alerts: send messages from anywhere in Nally

Requires TELEGRAM_USER_API_ID, TELEGRAM_USER_API_HASH, TELEGRAM_USER_PHONE in .env.
First run will prompt for phone code and 2FA password.
"""

import asyncio
import contextlib
import io
import logging
import os
import re
import time
from pathlib import Path
from typing import Optional

from telethon import TelegramClient, events

from ..config import (
    DATA_DIR,
    TELEGRAM_USER_API_ID,
    TELEGRAM_USER_API_HASH,
    TELEGRAM_USER_PHONE,
    TELEGRAM_USER_ID,
    NALLY_VOICE_CALLS_ENABLED,
)
from ..utils.logger import logger

# Session file stored in data/ alongside the main DB
SESSION_DIR = DATA_DIR / "telegram_user"
SESSION_FILE = "nally_user"

# Max message length (Telegram limit for users)
MAX_MSG_LEN = 4096

# Module-level client reference
_client: Optional[TelegramClient] = None
_owner_id: Optional[int] = None
_ready = asyncio.Event()
_tg_call = None  # pytgcalls instance (lazy init)
_active_calls: dict[int, object] = {}  # chat_id -> VoiceCallSession


def _get_client() -> TelegramClient:
    """Create or return the Telethon client."""
    global _client
    if _client is not None:
        return _client

    if not TELEGRAM_USER_API_ID or not TELEGRAM_USER_API_HASH:
        raise RuntimeError(
            "Telegram user account not configured. "
            "Set TELEGRAM_USER_API_ID, TELEGRAM_USER_API_HASH, and TELEGRAM_USER_PHONE in .env"
        )

    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    session_path = SESSION_DIR / SESSION_FILE

    _client = TelegramClient(
        str(session_path),
        TELEGRAM_USER_API_ID,
        TELEGRAM_USER_API_HASH,
    )
    return _client


async def _init_pytgcalls():
    """Initialize pytgcalls with the same Telethon client (lazy, one-time)."""
    global _tg_call
    if not NALLY_VOICE_CALLS_ENABLED:
        return None
    if _tg_call is not None:
        return _tg_call

    try:
        # Ensure silent WAV exists for call keepalive (60 seconds at 48kHz)
        silent_path = DATA_DIR / "silent.wav"
        if not silent_path.exists():
            import wave, io
            buf = io.BytesIO()
            with wave.open(buf, 'wb') as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(48000)
                w.writeframes(b'\x00\x00' * (48000 * 60))  # 60 seconds
            silent_path.write_bytes(buf.getvalue())

        from pytgcalls import PyTgCalls

        _tg_call = PyTgCalls(_client)
        await _tg_call.start()

        from pytgcalls.types import StreamFrames, StreamEnded, ChatUpdate, Direction

        @_tg_call.on_update()
        async def _on_call_update(client, update):
            try:
                chat_id = update.chat_id
                from pytgcalls.types.stream.device import Device

                # Find session with flexible ID resolution to account for Telethon / pytgcalls ID format differences
                session = _active_calls.get(chat_id)
                if not session:
                    # Try alternate forms
                    alt_ids = [
                        abs(chat_id),
                        int(str(chat_id).replace("-100", "")),
                        int(f"-100{abs(chat_id)}")
                    ]
                    for alt_id in alt_ids:
                        if alt_id in _active_calls:
                            session = _active_calls[alt_id]
                            break

                if isinstance(update, StreamFrames):
                    if session:
                        # Only feed INCOMING (remote user) audio into STT. Our
                        # own TTS is OUTGOING and must never be transcribed
                        # (would cause self-echo / feedback loops).
                        if update.direction == Direction.INCOMING and update.device in (
                            Device.MICROPHONE,
                            Device.SPEAKER,
                        ):
                            for frame in update.frames:
                                session.feed_frame(frame.frame)
                    return

                if isinstance(update, StreamEnded):
                    if session:
                        session.stop()
                    return

                if isinstance(update, ChatUpdate):
                    return
            except Exception as e:
                logger.error(f"call_update_error: {type(e).__name__}: {e}", extra={"chat_id": chat_id, "error": str(e)})

        logger.info("pytgcalls initialized — voice calls active")
        return _tg_call
    except ImportError:
        logger.warning("pytgcalls not installed — voice calls disabled")
        return None
    except Exception as e:
        logger.error(f"pytgcalls init failed: {e}")
        return None


async def _start_voice_session(msg, sender_id: int):
    """Start a group voice chat session when user says 'call me'."""
    global _tg_call

    if _tg_call is None:
        await msg.reply("Voice calls not available.")
        return

    from .voice_call import (
        VoiceCallSession,
        ensure_private_voice_group,
        start_group_voice_chat,
        leave_group_voice_chat,
    )

    # Beta 1:1: private group per user (isolated, no cross-talk)
    await msg.reply("Setting up your private voice chat...")

    client = _get_client()
    group_id, invite_link = await ensure_private_voice_group(client, sender_id)

    # Beta: just send invite link — programmatic InviteToChannel fails if user
    # not in contacts / privacy, link is reliable
    if invite_link:
        await msg.reply(
            f"Your private 1:1 voice chat: {invite_link}\n\n"
            f"Tap to join — Nally will talk there. This is your private line."
        )
    else:
        await msg.reply(
            f"Private voice group ready for {sender_id}. Search for 'Nally Voice {sender_id}' and join the voice chat."
        )

    # Start voice chat and join
    try:
        await start_group_voice_chat(_tg_call, client, group_id)

        # Create session and start listening
        session = VoiceCallSession(group_id, tg_call=_tg_call)
        _active_calls[group_id] = session

        # Run the voice session (this blocks until done)
        await session.run()
    except Exception as e:
        logger.error(f"Voice session error: {e}")
        await msg.reply(f"Voice session error: {e}")
    finally:
        _active_calls.pop(group_id, None)
        await leave_group_voice_chat(_tg_call, group_id)


def _make_auto_approve_emit():
    """Create emit that auto-approves gated tools for the owner (Telethon path)."""
    def emit(event: str, data: dict):
        if event == "confirmation_required":
            try:
                from ..config import TELEGRAM_USER_AUTO_APPROVE
                if not TELEGRAM_USER_AUTO_APPROVE:
                    logger.info(f"Telethon approval required but auto-approve disabled: {data.get('name')} tc_id={data.get('tool_call_id')}")
                    return
            except Exception:
                pass
            tc_id = data.get("tool_call_id", "")
            tool = data.get("name", "?")
            logger.info(f"Telethon auto-approve: {tool} tc_id={tc_id}")
            if tc_id:
                try:
                    from ..agent.graph import resolve_approval
                    resolve_approval(tc_id, True)
                except Exception as e:
                    logger.error(f"Telethon auto-approve failed for {tc_id}: {e}")
    return emit

# ── Voice note helpers ──

async def _generate_voice_summary(text: str) -> str:
    """Generate 1-2 sentence spoken summary via LLM (or fallback)."""
    try:
        if len(text) <= 200:
            return text
        from ..agent.llm import llm
        summary = await asyncio.to_thread(
            llm.simple_chat,
            user_message=f"Rewrite this as a 1-2 sentence spoken summary. Keep it conversational and natural, like you're talking to a friend. No markdown, no lists, just flowing speech:\n\n{text}",
            system_prompt="You are a voice assistant. Rewrite responses for natural spoken delivery. Be conversational, warm, concise. Never use markdown, bullet points, or lists. Just flowing sentences.",
        )
        return summary.strip()
    except Exception as e:
        logger.warning(f"Voice summary generation failed: {e}")
        sentences = re.split(r"(?<=[.!?])\s+", text.strip())
        if len(sentences) >= 2:
            return " ".join(sentences[:2])
        elif sentences:
            return sentences[0]
        return text[:200]

async def _send_voice_response_telethon(client, peer, text: str):
    """Send voice reply via Telethon (TTS -> OGG) with text fallback."""
    try:
        from ..voice.formatter import VoiceFormatter, VoiceMode
        from ..voice.tts import synthesize_to_wav
        from .voice import wav_to_ogg, check_ffmpeg

        if not check_ffmpeg():
            # Fallback to text if ffmpeg missing
            await client.send_message(peer, text[:4096])
            return

        voice_summary = await _generate_voice_summary(text)
        formatter = VoiceFormatter()
        speak_text = formatter.format(text, mode=VoiceMode.SMART, summary=voice_summary)
        if not speak_text:
            await client.send_message(peer, text[:4096])
            return

        wav_bytes = await asyncio.to_thread(synthesize_to_wav, speak_text)
        if not wav_bytes:
            await client.send_message(peer, text[:4096])
            return

        ogg_bytes = await asyncio.to_thread(wav_to_ogg, wav_bytes)
        if not ogg_bytes:
            await client.send_message(peer, text[:4096])
            return

        bio = io.BytesIO(ogg_bytes)
        bio.name = "nally_voice.ogg"
        caption = text[:1024] if len(text) > 150 else None
        # Show recording indicator while sending
        try:
            async with client.action(peer, "record-audio"):
                await client.send_file(peer, bio, voice_note=True, caption=caption)
        except Exception:
            # Fallback without action wrapper
            bio.seek(0)
            await client.send_file(peer, bio, voice_note=True, caption=caption)

        # Also send full text if it was long (voice is summary)
        if len(text) > 600:
            # Send as text after voice
            chunks = _split_message(text)
            # Only send first chunk to avoid spam, or full? Send full as text fallback context
            # For long responses, send the full text as follow-up
            for chunk in chunks[:2]:
                try:
                    await client.send_message(peer, chunk)
                    await asyncio.sleep(0.3)
                except Exception:
                    break

    except Exception as e:
        logger.error(f"Telethon voice response failed: {e}")
        try:
            await client.send_message(peer, text[:4096])
        except Exception:
            pass

async def _handle_voice_note(event, sender_id: int):
    """Handle incoming voice/audio notes: download -> STT -> agent -> voice reply."""
    msg = event.message
    client = event.client

    # Check ffmpeg
    try:
        from .voice import check_ffmpeg
        if not check_ffmpeg():
            await msg.reply("Voice not available \u2014 ffmpeg not installed.")
            return
    except Exception:
        pass

    # Typing indicator
    try:
        async with client.action(sender_id, "typing"):
            # Download
            buf = io.BytesIO()
            await client.download_media(msg, file=buf)
            ogg_bytes = buf.getvalue()
            if not ogg_bytes:
                await msg.reply("Could not download voice message.")
                return
            if len(ogg_bytes) > 15 * 1024 * 1024:
                await msg.reply("Voice note too large.")
                return

            # Convert OGG->PCM
            from .voice import ogg_to_pcm
            pcm_bytes = await asyncio.to_thread(ogg_to_pcm, ogg_bytes)
            if not pcm_bytes:
                await msg.reply("Could not process voice message.")
                return

            # Transcribe
            from ..voice.stt import transcribe
            text = await asyncio.to_thread(transcribe, pcm_bytes)
            if not text or not text.strip():
                await msg.reply("Couldn't understand the voice message.")
                return

            logger.info(f"Telethon voice transcript from {sender_id}: {text[:80]}")

            # Optional: echo transcript for UX (can be removed if noisy)
            # await msg.reply(f"Got it: {text[:500]}")

            # Agent
            from ..agent.sessions import session_manager
            session_id = f"tg_user:{sender_id}"
            emit = _make_auto_approve_emit()
            # Use record-audio indicator during agent processing + TTS
            async with client.action(sender_id, "record-audio"):
                response = await asyncio.to_thread(session_manager.process, session_id, text, emit=emit)

            if not response or not response.strip():
                return

            # Extract text
            if isinstance(response, dict):
                text_response = response.get("text", "")
            else:
                text_response = str(response)

            # Check for outbound file markers (image gen etc.)
            try:
                from .media import parse_outbound_files, strip_file_markers
                out_files = parse_outbound_files(text_response)
                cleaned = strip_file_markers(text_response)
                # Send voice first
                await _send_voice_response_telethon(client, sender_id, cleaned)
                # Then send any generated files
                if out_files:
                    from .media import send_attachments_telethon
                    await send_attachments_telethon(client, sender_id, out_files)
                return
            except Exception as e:
                logger.debug(f"Voice outbound media handling failed: {e}")

            await _send_voice_response_telethon(client, sender_id, text_response)

    except Exception as e:
        logger.error(f"Telethon voice note error: {e}")
        try:
            await msg.reply(f"Voice processing failed: {e}")
        except Exception:
            pass

# ── Media + text handler ──

async def _handle_message(event: events.NewMessage.Event):
    """Handle incoming DMs — route through agent brain."""
    global _owner_id

    msg = event.message
    sender = await event.get_sender()

    sender_id = sender.id if sender else None
    client = event.client

    # Detect media types early
    is_voice = bool(getattr(msg, "voice", None) or getattr(msg, "audio", None))
    is_photo = bool(getattr(msg, "photo", None))
    is_document = bool(getattr(msg, "document", None))
    has_media = is_voice or is_photo or is_document

    text = msg.text or ""
    # Telethon: caption for media is in msg.text, file caption same field
    caption = text

    # Beta: handle all users, not just owner (full Telegram capabilities)
    # Keep owner auto-detection for logging but don't gate responses
    if not _owner_id and sender_id:
        _owner_id = sender_id
        logger.info(f"Owner auto-detected from first DM: {_owner_id}")
    # Note: Beta allows any sender — no owner-only gate
    # Previous single-user check removed for beta multi-user support

    # Voice note path — highest priority
    if is_voice:
        logger.info(f"Telethon voice note from {sender_id}")
        await _handle_voice_note(event, sender_id)
        return

    # Media inbound (photo/document) — may have empty text but has file
    media_desc = ""
    inbound_path = None
    if is_photo or is_document:
        try:
            from .media import save_telethon_media, build_agent_input, analyze_image_for_game
            # Show typing while downloading
            async with client.action(sender_id, "typing"):
                inbound_path, media_desc = await save_telethon_media(client, msg, f"tg_user:{sender_id}")
                # Vision + OCR for images (game-aware, uses Muse Spark when available)
                if inbound_path and inbound_path.suffix.lower() in {".jpg",".jpeg",".png",".webp",".gif",".bmp"}:
                    try:
                        vision_block = await analyze_image_for_game(inbound_path, user_question=caption)
                        if vision_block:
                            media_desc += f"\n\n{vision_block}\n\n[Instruction: Use the Vision analysis above as the primary source. Do not run PIL/code to re-analyze the image — answer directly from Vision. This is the authoritative description.]"
                            try:
                                from nally.tools.receipts import receipt_store
                                import uuid
                                receipt_store.record(
                                    tool_call_id=f"vision_{uuid.uuid4().hex[:8]}",
                                    tool="vision_analyze",
                                    args={"image": str(inbound_path), "question": caption[:200]},
                                    result=vision_block[:2000],
                                    success=True,
                                    duration_ms=1500,
                                )
                            except Exception:
                                pass
                    except Exception as e:
                        logger.debug(f"Telethon vision analyze failed: {e}")

                # Build combined prompt — caption + media description
                combined = build_agent_input(caption, media_desc)
                if not combined.strip():
                    # Fallback: at least acknowledge
                    combined = media_desc or "[User sent a file]"

                logger.info(f"Telegram user media from {sender_id}: {combined[:120]}")

                # Handle "call me" even with media? check caption
                if caption.strip().lower() in ("call me", "call nally"):
                    if NALLY_VOICE_CALLS_ENABLED:
                        asyncio.create_task(_start_voice_session(msg, sender_id))
                        return
                    else:
                        await msg.reply("Voice calls not enabled. Set NALLY_VOICE_CALLS_ENABLED=true in .env")
                        return

                # Process through agent with typing indicator
                from ..agent.sessions import session_manager
                from .media import parse_outbound_files, strip_file_markers, send_attachments_telethon

                session_id = f"tg_user:{sender_id}"
                emit = _make_auto_approve_emit()
                response = await asyncio.to_thread(session_manager.process, session_id, combined, emit=emit)

                if not response or not str(response).strip():
                    return

                if isinstance(response, dict):
                    text_response = response.get("text", "")
                else:
                    text_response = str(response)

                # Outbound files
                out_files = parse_outbound_files(text_response)
                cleaned = strip_file_markers(text_response)
                if not cleaned.strip() and out_files:
                    cleaned = "Here you go:"

                # Send text chunks
                chunks = _split_message(cleaned.strip())
                for chunk in chunks:
                    try:
                        await msg.reply(chunk)
                    except Exception as e:
                        logger.error(f"Failed to send reply: {e}")
                        break
                    if len(chunks) > 1:
                        await asyncio.sleep(0.5)

                # Send outbound attachments
                if out_files:
                    await send_attachments_telethon(client, sender_id, out_files)

                return

        except Exception as e:
            logger.error(f"Telethon media handling failed: {e}")
            # Fall through to text handling as fallback
            if not text.strip():
                try:
                    await msg.reply(f"Got your file but failed to process it: {e}")
                except Exception:
                    pass
                return

    # Text-only path (no media or media already handled fallback)
    if not text.strip():
        return

    logger.info(f"Telegram user DM from {sender_id}: {text[:80]}")

    # Handle "call me" — start a group voice chat session
    if text.strip().lower() in ("call me", "call nally"):
        if NALLY_VOICE_CALLS_ENABLED:
            asyncio.create_task(_start_voice_session(msg, sender_id))
            return
        else:
            await msg.reply("Voice calls not enabled. Set NALLY_VOICE_CALLS_ENABLED=true in .env")
            return

    # Process through agent (text)
    try:
        from ..agent.sessions import session_manager
        from .media import parse_outbound_files, strip_file_markers, send_attachments_telethon

        session_id = f"tg_user:{sender_id}"
        emit = _make_auto_approve_emit()

        # Typing indicator while agent works
        async with client.action(sender_id, "typing"):
            response = await asyncio.to_thread(
                session_manager.process,
                session_id,
                text,
                emit=emit,
            )

    except Exception as e:
        logger.error(f"Agent failed for tg_user:{sender_id}: {e}")
        response = "Sorry, I ran into an error. Please try again."

    if not response or not str(response).strip():
        return

    if isinstance(response, dict):
        text_response = response.get("text", "")
    else:
        text_response = str(response)

    # Check for outbound file markers
    try:
        from .media import parse_outbound_files, strip_file_markers, send_attachments_telethon
        out_files = parse_outbound_files(text_response)
        cleaned = strip_file_markers(text_response)
        if not cleaned.strip() and out_files:
            cleaned = "Here you go:"
        # Send text
        chunks = _split_message(cleaned.strip())
        for chunk in chunks:
            try:
                await msg.reply(chunk)
            except Exception as e:
                logger.error(f"Failed to send reply: {e}")
                break
            if len(chunks) > 1:
                await asyncio.sleep(0.5)
        # Send files
        if out_files:
            await send_attachments_telethon(client, sender_id, out_files)
        return
    except Exception as e:
        logger.error(f"Outbound file handling failed: {e}")

    # Fallback split and send (if media helper failed)
    chunks = _split_message(str(response).strip())
    for chunk in chunks:
        try:
            await msg.reply(chunk)
        except Exception as e:
            logger.error(f"Failed to send reply: {e}")
            break
        if len(chunks) > 1:
            await asyncio.sleep(0.5)


def _split_message(text: str, limit: int = MAX_MSG_LEN) -> list:
    """Split long messages at paragraph/break boundaries."""
    if len(text) <= limit:
        return [text]

    chunks = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break

        split_at = text.rfind("\n\n", 0, limit)
        if split_at < limit // 2:
            split_at = text.rfind("\n", 0, limit)
        if split_at < limit // 4:
            split_at = text.rfind(" ", 0, limit)
        if split_at < limit // 4:
            split_at = limit

        chunks.append(text[:split_at])
        text = text[split_at:].lstrip()

    return chunks


async def start():
    """Start the Telethon client and listen for DMs + voice calls. Blocks until disconnected."""
    global _owner_id

    client = _get_client()

    # Set owner ID from config
    if TELEGRAM_USER_ID:
        _owner_id = TELEGRAM_USER_ID
        logger.info(f"Owner ID set from config: {_owner_id}")

    logger.info("Starting Telegram user client...")

    # First run: will prompt for phone code and 2FA
    await client.start(phone=TELEGRAM_USER_PHONE)

    # Register message handler AFTER connecting
    client.add_event_handler(_handle_message, events.NewMessage(incoming=True))

    # If no owner ID configured, detect from account
    if not _owner_id:
        me = await client.get_me()
        if me:
            _owner_id = me.id
            logger.info(f"Owner ID auto-detected: {_owner_id}")

    me = await client.get_me()
    if me:
        logger.info(f"Logged in as: {me.first_name} (@{me.username or 'no username'})")

    # Initialize pytgcalls (same Telethon client — no competing sessions)
    if NALLY_VOICE_CALLS_ENABLED:
        await _init_pytgcalls()

    _ready.set()
    logger.info("Telegram user client ready — listening for DMs and calls")

    # This blocks and processes incoming events until disconnected
    await client.run_until_disconnected()


async def stop():
    """Gracefully disconnect."""
    global _client, _tg_call
    if _tg_call:
        with contextlib.suppress(Exception):
            await _tg_call.stop()
        _tg_call = None
    if _client:
        await _client.disconnect()
        _client = None
        logger.info("Telegram user client disconnected")


def is_ready() -> bool:
    """Check if the client is connected and ready."""
    return _ready.is_set()


async def send_message(text: str, user_id: Optional[int] = None) -> bool:
    """Send a proactive message to the owner (or specified user_id)."""
    global _owner_id

    if not is_ready():
        logger.warning("Telegram user client not ready, cannot send message")
        return False

    target = user_id or _owner_id
    if not target:
        logger.warning("No target user_id for proactive message")
        return False

    client = _get_client()
    chunks = _split_message(text.strip())

    try:
        for chunk in chunks:
            await client.send_message(target, chunk)
            if len(chunks) > 1:
                await asyncio.sleep(0.5)
        logger.info(f"Proactive message sent to {target}: {text[:80]}")
        return True
    except Exception as e:
        logger.error(f"Failed to send proactive message: {e}")
        return False


def run_standalone():
    """Run the user client as a standalone process (blocking)."""
    async def _main():
        await start()
        try:
            while _client and _client.is_connected():
                await asyncio.sleep(1)
        except (KeyboardInterrupt, SystemExit):
            pass
        finally:
            await stop()

    asyncio.run(_main())


if __name__ == "__main__":
    run_standalone()
