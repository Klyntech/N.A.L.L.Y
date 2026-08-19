# Voice Mode

Nally supports push-to-talk voice interaction with speech-to-text (STT) and text-to-speech (TTS).

## How It Works

```
User speaks → Microphone → STT (Groq Whisper / faster-whisper) → Agent → TTS (Piper/ElevenLabs/FishAudio) → Audio output
```

## Running Voice Mode

```bash
python main.py --voice
```

This starts the voice interaction loop — push-to-talk with keyboard trigger.

## Components

| Component | File | Purpose |
|-----------|------|---------|
| STT | `nally/voice/stt.py` | Batch STT: Groq Whisper API first, faster-whisper local (`tiny`) fallback, plus `DeepgramStreamingSTT` for realtime |
| TTS | `nally/voice/tts.py` | Text-to-speech via Piper, ElevenLabs, or FishAudio |
| Formatter | `nally/voice/formatter.py` | Text cleanup for speech (removes markdown, code blocks, substitutes link text) |
| Speech preprocessing | `nally/voice/speech_pipeline.py` | Text preprocessing, sentence splitting, prosody, emotion detection |
| Loop | `nally/voice/loop.py` | Push-to-talk interaction loop |
| Streaming pipeline | `nally/voice/pipeline.py` | `VoicePipeline` — overlapped realtime streaming STT → TTS with barge-in |
| Barge-in | `nally/voice/bargein.py` | `BargeInDetector` — interrupt TTS on sustained user speech (`barge_in.py` is legacy) |
| LiveKit agent | `nally/voice/livekit_agent.py` | VoIP agent for LiveKit SIP calls |
| Metrics | `nally/voice/metrics.py` | Latency/error metrics (OpenTelemetry/Prometheus) |

## STT (Speech-to-Text)

Batch transcription (`transcribe()`) tries the **Groq Whisper API first**
(`whisper-large-v3-turbo`, requires `GROQ_API_KEY`) and falls back to local
[Faster-Whisper](https://github.com/SYSTRAN/faster-whisper). Note the local
model is hard-coded to `tiny` — it does not use the larger models below.

For real-time streaming (Telegram voice calls, LiveKit), `DeepgramStreamingSTT`
uses the Deepgram Flux WebSocket API (`DEEPGRAM_API_KEY`).

### Requirements

- Python package: `faster-whisper`
- RAM: 2-4 GB (base model)
- First run downloads model (~75 MB for `tiny`, ~150 MB for `base`)
- GPU optional (CUDA) for faster transcription

### Models

The local fallback uses `tiny` only. The following sizes are for reference if you
edit the `WhisperModel(...)` call in `nally/voice/stt.py`:

| Model | Size | Speed | Quality |
|-------|------|-------|---------|
| `tiny` | 75 MB | Fastest | Basic |
| `base` | 150 MB | Fast | Good |
| `small` | 466 MB | Medium | Better |
| `medium` | 1.5 GB | Slow | Great |
| `large-v3` | 3 GB | Slowest | Best |

## TTS (Text-to-Speech)

### Piper (Default)

Local, free, no API key required.

```env
NALLY_TTS_BACKEND=piper
```

- First run downloads voice model
- Models stored in `data/voice/`
- Supports multiple voices and languages
- Low latency — runs locally

### ElevenLabs

Cloud-based, high-quality voices. `ELEVENLABS_MODEL` defaults to
`eleven_multilingual_v2` (matches `nally/config.py`; `.env.example` was
previously misaligned on this and is now aligned).

```env
NALLY_TTS_BACKEND=elevenlabs
ELEVENLABS_API_KEY=your-key
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM  # Rachel (default)
ELEVENLABS_MODEL=eleven_multilingual_v2
```

### FishAudio

Cloud TTS via the Fish Audio SDK — premium quality, ultra-low latency.
Uses `FISH_API_KEY` (required), optional `FISH_VOICE_ID` (blank = model
default), and `FISH_MODEL` (default `s2.1-pro-free`).

```env
NALLY_TTS_BACKEND=fishaudio
FISH_API_KEY=your-key
FISH_VOICE_ID=                # optional; blank = model's default voice
FISH_MODEL=s2.1-pro-free
```

### Text Formatting for Speech

The `VoiceFormatter` cleans text before TTS:

- Removes markdown formatting (**bold**, *italic*, `code`)
- Strips code blocks
- Replaces markdown links with their **link text** (keeps `[text](url)` → `text`)
- Expands abbreviations
- Handles numbers and symbols

## Web Voice (Browser)

The web frontend supports voice input via WebSocket:

1. User clicks mic button
2. Browser captures audio (webm/Opus format)
3. Sent to backend via `WS /ws/{session_id}`
4. Backend: webm → ffmpeg → PCM → STT → agent → TTS → WAV → base64
5. Audio played back in browser

### Requirements for Web Voice

- Browser: Chrome, Edge, or Firefox (MediaRecorder API)
- HTTPS required for mic access (except localhost)
- ffmpeg installed on server (for audio conversion)

## Telegram Voice

The Telegram bot supports voice messages:

1. User sends voice message to bot
2. Telegram provides OGG/Opus audio
3. Backend: OGG → PCM (via ffmpeg) → STT → agent → reply
4. Optional: reply with voice (TTS → OGG → Telegram)

### Real-Time Voice Calls

Beyond voice *messages*, Nally also supports real-time 1-on-1 voice *calls* via
pytgcalls. Run with `python run_tg_call.py`, gated by
`NALLY_VOICE_CALLS_ENABLED=true` (plus `TELEGRAM_USER_*` credentials):

- `nally/telegram/voice_call.py` — `VoiceCallSession` using group voice chats
- Audio runs through `VoicePipeline`: Deepgram streaming STT + Silero VAD +
  Fish/ElevenLabs streaming TTS + `BargeInDetector`
- Requires: `pytgcalls[telethon]`, `silero-vad`, `torch`, `DEEPGRAM_API_KEY`

## Troubleshooting

### No audio input
- Check microphone permissions in OS/browser
- Verify `sounddevice` is installed: `pip install sounddevice`
- On Linux: ensure PulseAudio or ALSA is running

### STT not transcribing
- Batch STT uses Groq Whisper first — check `GROQ_API_KEY`
- Local fallback uses the `tiny` model — first run downloads it, check internet connection
- Check logs for CUDA errors if using GPU
- The model is hard-coded to `tiny`; edit `WhisperModel(...)` in `nally/voice/stt.py` for a larger one

### TTS not speaking
- **Piper**: Check `data/voice/` exists and has model files
- **ElevenLabs**: Verify API key is valid and has credits
- **FishAudio**: Verify `FISH_API_KEY` is set and valid
- Check audio output device is connected

### Poor voice quality
- Try larger Whisper model for STT
- Switch to ElevenLabs for TTS
- Check microphone quality and environment noise

### ffmpeg not found
- Install ffmpeg: `apt install ffmpeg` (Linux), `choco install ffmpeg` (Windows), `brew install ffmpeg` (macOS)
- Required for web voice and Telegram voice
