"""Nally Voice I/O — push-to-talk voice interface.


Phase 1: push-to-talk loop using local STT (faster-whisper) and TTS (Piper).
All voice backends are swappable without touching the agent — see stt.py / tts.py.
"""


def run_voice_loop(session_id: str = "voice:default"):
    """Launch the push-to-talk voice loop. Blocks until user exits."""
    from .loop import run_voice_loop as _run

    return _run(session_id)
