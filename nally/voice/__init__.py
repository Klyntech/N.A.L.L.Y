"""Nally Voice I/O — bot voice notes only.

Live paths (VoicePipeline, LiveKit, Telethon, barge-in) have been removed.
Remaining voice is Telegram Bot API voice notes via speech_output adapter:

  Bot reply text → VoiceFormatter → SpeechPlanner → speech_output
  → Fish/ElevenLabs streaming → WAV → OGG → reply_voice

All backends remain swappable via stt.py / tts.py.
"""
