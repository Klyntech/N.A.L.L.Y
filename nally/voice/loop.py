"""Push-to-talk voice loop for Nally.

Hold SPACE to record, release to send. Nally processes through the same
session_manager.process() pipeline as web/CLI — same permission gate,
same memory, same history. Tool approval prompts are spoken and answered
inline via the emit("confirmation_required", ...) callback.
"""

import logging
import time

import numpy as np

logger = logging.getLogger("nally.voice.loop")

SAMPLE_RATE = 16000
CHANNELS = 1
PTT_KEY = "space"
APPROVAL_LISTEN_SECONDS = 3


# ── Package gate ───────────────────────────────────────────


def _check_dependencies():
    """Return a list of missing packages, or [] if all present."""
    missing = []
    for pkg, label in [
        ("keyboard", "keyboard"),
        ("sounddevice", "sounddevice"),
        ("faster_whisper", "faster-whisper"),
        ("piper", "piper-tts"),
    ]:
        try:
            __import__(pkg)
        except ImportError:
            missing.append(label)
    return missing


# ── Approval handler (called from emit inside agent thread) ─


def _handle_approval(data: dict):
    """Speak the approval request, record a yes/no response, resolve."""
    import sounddevice as sd

    from . import stt, tts

    tool_name = data.get("name", "unknown")
    tool_args = data.get("args", {})
    tool_call_id = data.get("tool_call_id", "")

    # Build a human-readable prompt
    if tool_name == "run_command":
        cmd = tool_args.get("command", "")
        prompt = f"Run command: {cmd}.  Say yes to approve, or no to deny."
    elif tool_name == "file_ops":
        action = tool_args.get("action", "")
        fp = tool_args.get("file_path", "")
        prompt = f"{action} file {fp}.  Say yes to approve, or no to deny."
    else:
        prompt = f"Approve {tool_name}?  Say yes or no."

    print(f"\n  [APPROVAL] {prompt}")
    tts.speak(prompt)

    # Record response
    print("  Waiting for voice response...", end="", flush=True)
    chunks = []
    with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32") as stream:
        for _ in range(int(APPROVAL_LISTEN_SECONDS * SAMPLE_RATE / 1024)):
            data, _ = stream.read(1024)
            chunks.append(data.copy())

    audio = np.concatenate(chunks, axis=0).flatten()
    response_text = stt.transcribe(audio.tobytes())
    print(f' "{response_text}"')

    yes_words = {"yes", "yeah", "yep", "approve", "ok", "okay", "sure", "do it", "confirm"}
    no_words = {"no", "nope", "deny", "cancel", "stop", "nah", "negative"}

    words = set(response_text.lower().split())
    approved = bool(words & yes_words)
    denied = bool(words & no_words)

    if approved:
        print("  -> Approved")
        tts.speak("Approved.")
    elif denied:
        print("  -> Denied")
        tts.speak("Denied.")
    else:
        print("  -> Unclear, denying by default")
        tts.speak("Unclear response, denying by default.")
        approved = False

    from ..agent.graph import resolve_approval

    resolve_approval(tool_call_id, approved)


# ── Main loop ──────────────────────────────────────────────


def run_voice_loop(session_id: str = "voice:default"):
    """Blocking push-to-talk voice loop.

    Keys:
        SPACE (hold) — record while held, release to send
        Ctrl+C       — exit
    """
    missing = _check_dependencies()
    if missing:
        print(f"Voice mode requires packages not installed: {', '.join(missing)}")
        print(f"Install them with:  pip install {' '.join(missing)}")
        return

    import keyboard
    import sounddevice as sd

    from . import stt, tts
    from .formatter import format_for_voice

    print()
    print("=" * 50)
    print("  N A L L Y   V O I C E   M O D E")
    print("=" * 50)
    print()
    print("  Hold SPACE to talk, release to send.")
    print("  Press Ctrl+C to exit.")
    print()

    while True:
        try:
            # ── Wait for push-to-talk ──
            print("Ready. Hold SPACE to start recording...")
            while not keyboard.is_pressed(PTT_KEY):
                time.sleep(0.01)

            # ── Record while held ──
            print("Listening...", end="", flush=True)
            chunks = []
            with sd.InputStream(samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="float32") as stream:
                while keyboard.is_pressed(PTT_KEY):
                    data, _ = stream.read(1024)
                    chunks.append(data.copy())

            if not chunks:
                print(" (no audio)")
                continue

            audio = np.concatenate(chunks, axis=0).flatten()
            duration = len(audio) / SAMPLE_RATE
            print(f" ({duration:.1f}s)")

            if duration < 0.3:
                print("Too short, try again.")
                continue

            # ── Transcribe ──
            print("Transcribing...", end="", flush=True)
            text = stt.transcribe(audio.tobytes())
            print(f' "{text}"')

            if not text.strip():
                continue

            if text.lower().strip() in ("quit", "exit", "bye", "goodbye"):
                print("\nNally: Goodbye!")
                tts.speak("Goodbye!")
                break

            # ── Process through agent ──
            print("Thinking...", end="", flush=True)

            def emit_handler(event, data):
                if event == "confirmation_required":
                    _handle_approval(data)

            from ..agent.sessions import session_manager

            response = session_manager.process(session_id, text, emit=emit_handler)
            print(f"\nNally: {response}")

            # ── Speak reply ──
            tts.speak(format_for_voice(response))
            print()

        except KeyboardInterrupt:
            print("\n\nNally: Goodbye!")
            break
        except Exception as e:
            print(f"\nError: {e}")
            logger.error(f"Voice loop error: {e}", exc_info=True)
