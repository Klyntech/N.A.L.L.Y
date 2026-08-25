"""Nally Voice I/O — push-to-talk voice interface.

Phase 1: push-to-talk loop using STT (Groq API + faster-whisper fallback) and TTS (Piper/ElevenLabs).
All voice backends are swappable without touching the agent — see stt.py / tts.py.

Speech Pipeline (speech_pipeline.py):
- Sentence boundary detection (handles abbreviations, decimals, initials)
- Text preprocessing (URLs, emails, dates, abbreviations → spoken form)
- Pronunciation dictionary (90+ entries)
- Emotion detection (urgent, empathetic, confident, curious, informative)
- Voice profiles (nally, narrator, concise, warm)
- Prosody smoothing (exponential moving average)
"""


def run_voice_loop(session_id=None):
    """Launch the push-to-talk voice loop. Blocks until user exits.

    session_id defaults to the owner's shared brain session.
    """
    from .loop import run_voice_loop as _run

    return _run(session_id)
