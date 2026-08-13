# Voice Mode

Nally supports push-to-talk voice interaction with speech-to-text (STT) and text-to-speech (TTS).

## How It Works

```
User speaks → Microphone → STT (Faster-Whisper) → Agent → TTS (Piper/ElevenLabs) → Audio output
```

## Running Voice Mode

```bash
python main.py --voice
```

This starts the voice interaction loop — push-to-talk with keyboard trigger.

## Components

| Component | File | Purpose |
|-----------|------|---------|
| STT | `nally/voice/stt.py` | Speech-to-text via Faster-Whisper |
| TTS | `nally/voice/tts.py` | Text-to-speech via Piper or ElevenLabs |
| Formatter | `nally/voice/formatter.py` | Text cleanup for speech (removes markdown, code blocks) |
| Loop | `nally/voice/loop.py` | Push-to-talk interaction loop |
| Pipeline | `nally/voice/speech_pipeline.py` | End-to-end speech pipeline |

## STT (Speech-to-Text)

Uses [Faster-Whisper](https://github.com/SYSTRAN/faster-whisper) (optimized Whisper implementation).

### Requirements

- Python package: `faster-whisper`
- RAM: 2-4 GB (base model)
- First run downloads model (~150 MB for base)
- GPU optional (CUDA) for faster transcription

### Models

| Model | Size | Speed | Quality |
|-------|------|-------|---------|
| `tiny` | 75 MB | Fastest | Basic |
| `base` | 150 MB | Fast | Good (default) |
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
- Models stored in `data/piper/`
- Supports multiple voices and languages
- Low latency — runs locally

### ElevenLabs

Cloud-based, high-quality voices.

```env
NALLY_TTS_BACKEND=elevenlabs
ELEVENLABS_API_KEY=your-key
ELEVENLABS_VOICE_ID=21m00Tcm4TlvDq8ikWAM  # Rachel (default)
ELEVENLABS_MODEL=eleven_multilingual_v2
```

### Text Formatting for Speech

The `VoiceFormatter` cleans text before TTS:

- Removes markdown formatting (**bold**, *italic*, `code`)
- Strips code blocks
- Removes URLs (says "link" instead)
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

## Troubleshooting

### No audio input
- Check microphone permissions in OS/browser
- Verify `sounddevice` is installed: `pip install sounddevice`
- On Linux: ensure PulseAudio or ALSA is running

### STT not transcribing
- First run downloads model — check internet connection
- Check logs for CUDA errors if using GPU
- Try smaller model if RAM is limited

### TTS not speaking
- **Piper**: Check `data/piper/` exists and has model files
- **ElevenLabs**: Verify API key is valid and has credits
- Check audio output device is connected

### Poor voice quality
- Try larger Whisper model for STT
- Switch to ElevenLabs for TTS
- Check microphone quality and environment noise

### ffmpeg not found
- Install ffmpeg: `apt install ffmpeg` (Linux), `choco install ffmpeg` (Windows), `brew install ffmpeg` (macOS)
- Required for web voice and Telegram voice
