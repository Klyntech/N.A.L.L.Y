"""Nally Telegram User Account — Telethon client for DMs + voice calls.

Real Telegram user account (not a bot). Only interacts with the configured
owner. Supports:
- Incoming DMs: process through agent brain, reply as text
- Incoming voice calls: auto-answer, VAD → STT → agent → TTS with barge-in
- "call me" DM: initiate an outgoing voice call
- Proactive alerts: send messages from anywhere in Nally

Requires TELEGRAM_USER_API_ID, TELEGRAM_USER_API_HASH, TELEGRAM_USER_PHONE in .env.
First run will prompt for phone code and 2FA password.
"""

import asyncio
import contextlib
import logging
import os
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
        ensure_voice_chat_group,
        start_group_voice_chat,
        leave_group_voice_chat,
    )

    # Ensure we have a voice chat group
    await msg.reply("Setting up voice chat...")

    client = _get_client()
    group_id, invite_link = await ensure_voice_chat_group(client)

    # Add user to the group so they can join
    try:
        from telethon.tl.functions.messages import AddChatUserRequest
        await client.invoke(
            AddChatUserRequest(
                user_id=sender_id,
                fwd_limit=0,
            )
        )
    except Exception as e:
        logger.warning(f"Could not add user to group (may already be in): {e}")
        # Try alternative: invite user via channel invite link
        try:
            from telethon.tl.functions.channels import InviteToChannelRequest
            await client.invoke(
                InviteToChannelRequest(
                    channel=group_id,
                    users=[sender_id],
                )
            )
        except Exception as e2:
            logger.warning(f"Could not invite user to group: {e2}")

    # Send invite link
    if invite_link:
        await msg.reply(
            f"Join the voice chat here: {invite_link}\n\n"
            f"Once you join, I'll start talking."
        )
    else:
        await msg.reply(
            f"Voice chat group created. Search for 'Nally Voice' in your Telegram groups."
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


async def _handle_message(event: events.NewMessage.Event):
    """Handle incoming DMs — route through agent brain."""
    global _owner_id

    msg = event.message
    sender = await event.get_sender()

    sender_id = sender.id if sender else None
    text = msg.text or ""
    if not text.strip():
        return

    # Auto-detect owner from first message if not configured
    if not _owner_id and sender_id:
        _owner_id = sender_id
        logger.info(f"Owner auto-detected from first DM: {_owner_id}")

    # Only respond to the owner
    if _owner_id and sender_id != _owner_id:
        logger.debug(f"Ignoring message from non-owner: {sender_id}")
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

    # Process through agent
    try:
        from ..agent.sessions import session_manager

        session_id = f"tg_user:{sender_id}"
        response = await asyncio.to_thread(
            session_manager.process,
            session_id,
            text,
            emit=lambda e, d: None,  # no-op emit for user account
        )
    except Exception as e:
        logger.error(f"Agent failed for tg_user:{sender_id}: {e}")
        response = "Sorry, I ran into an error. Please try again."

    if not response or not response.strip():
        return

    # Split and send
    chunks = _split_message(response.strip())
    for chunk in chunks:
        try:
            await msg.reply(chunk)
        except Exception as e:
            logger.error(f"Failed to send reply: {e}")
            break

        # Small delay between chunks to avoid rate limits
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
