# LiveKit SIP Setup — Zero-Cost Phone Calls for Nally

Dial Nally from any free SIP app (e.g. Linphone) and get a real-time voice
conversation with the full Nally brain. No Twilio, no per-minute VoIP charges —
it runs on the **LiveKit Cloud free tier** with a SIP Inbound Trunk.

```
[Linphone] --SIP--> [LiveKit SIP Ingress] --WebRTC--> [nally.voice.livekit_agent]
        <--audio--                      <--audio--          (voice/stt.py, voice/tts.py)
```

## How it works

1. LiveKit Cloud terminates the call: a phone number / SIP endpoint rings the
   trunk you configure.
2. The trunk bridges the SIP caller into a LiveKit room as a participant.
3. `nally/voice/livekit_agent.py` joins that room, hears the caller, sends the
   speech through the existing STT → `session_manager.process` → TTS pipeline,
   and speaks the reply back over the call.

## 1. Create a LiveKit Cloud project (free tier)

1. Go to <https://cloud.livekit.io> and sign up (free tier includes SIP trunks).
2. Create a new project. Note the project name — it becomes the subdomain,
   e.g. project `nally` → URL `wss://nally.livekit.cloud`.
3. Open **Settings → Keys**:
   - Copy the **API Key** (starts with `API...`).
   - Copy the **API Secret**.
   - Copy the **WebSocket URL** (`wss://<project>.livekit.cloud`).
4. Optionally set `LIVEKIT_URL`, `LIVEKIT_API_KEY`, `LIVEKIT_API_SECRET` in
   your `.env`. If unset, the agent reads them from your environment.

## 2. Enable SIP Ingress

1. In the LiveKit Cloud dashboard open **SIP** (left sidebar) → **Inbound Trunks**.
2. **Create Inbound Trunk**:
   - **Trunk Name**: `nally`
   - **Number**: your chosen extension/phone number, e.g. `+15551234567`
   - **Allowed Phone Numbers**: `*` (or restrict to the numbers you will call from)
   - **Room Name**: leave blank (agent auto-joins the room created per call), or
     set a fixed room name like `nally-call`
   - **Authentication**: choose a PIN or IP allow-list (free tier supports both)
   - Save the trunk.
3. Copy the **SIP Endpoint** shown for the trunk — it looks like
   `sip:sip-nally@us-east-1.sip.livekit.cloud` (or a per-trunk subdomain).
   This is the address your phone app dials.

## 3. Configure Linphone (free SIP client)

1. Install Linphone (Android / iOS / desktop) from <https://www.linphone.org>.
2. Open **Settings → Account / SIP Account** and **Add SIP account**:
   - **SIP Address**: `sip:nally@sip-nally@us-east-1.sip.livekit.cloud`
     (use the **Username** you set on the trunk, and the **SIP Endpoint** you copied)
   - **Username**: the trunk username (e.g. `nally`)
   - **Password**: the trunk PIN you configured in step 2
   - **Domain / Proxy**: the trunk host from the SIP Endpoint
3. Save. The account should register (green dot).
4. Dial the **Number** from step 2 (`+15551234567`) and press call.

If the call connects but you get no audio, check that the LiveKit WebSocket URL
in `.env` matches your project and that you enabled SIP on the project.

## 4. Run the agent

```bash
pip install -r requirements.txt
python -m nally.voice.livekit_agent
```

The agent logs in as `nally-voip`, joins the room the SIP trunk creates, greets
the caller, and the conversation starts.

### Options

- `DEEPGRAM_API_KEY` — enables **streaming** STT (lower latency). Without it,
  the agent falls back to the existing batch STT (`voice/stt.py`, Groq/local).
- `NALLY_VOIP_STREAMING_STT=false` — force batch STT even if a Deepgram key is set.
- `NALLY_VOIP_TTS=plugin` — use the LiveKit ElevenLabs plugin for TTS
  (needs `ELEVENLABS_API_KEY`). Default is the existing
  `NALLY_TTS_BACKEND` (Piper/ElevenLabs) via `voice/tts.py`.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| Call drops immediately | Check the agent is running and `LIVEKIT_URL` matches the project. |
| No greeting heard | Confirm the SIP trunk routes into a room the agent joins (`auto_subscribe=AUDIO_ONLY`). |
| Agent can't hear caller | Ensure the caller's mic is unmuted; VAD needs `min_speech_duration=0.2`. |
| Approvals not answered | Nally speaks a yes/no prompt; say "yes" or "no" — see `_classify_yes_no`. |

## Costs

- **LiveKit Cloud free tier**: 10,000 audio minutes/month (no charge for SIP
  trunks on free tier).
- **Linphone**: free.
- **STT**: local faster-whisper is free; Groq/Deepgram have their own free tiers.
- **TTS**: Piper is fully local and free; ElevenLabs has a free tier.

No Twilio SDK is used anywhere in this project.
