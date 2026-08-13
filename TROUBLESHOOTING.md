# Troubleshooting

Common issues and how to fix them.

## Server Won't Start

### "NALLY_ACCESS_TOKEN is not set"
Your `.env` file is missing the access token. Add:
```env
NALLY_ACCESS_TOKEN=your-secret-token
```

### "API key not configured for provider"
Check your `.env` has the correct key for your provider:
- `NALLY_PROVIDER=opencode` → needs `OPENCODE_API_KEY`
- `NALLY_PROVIDER=groq` → needs `GROQ_API_KEY`

### Port already in use
Change the port:
```bash
python main.py --port 8080
```

## Chat Not Working

### No response / timeout
- Check your LLM provider API key is valid
- Check your internet connection
- Look at server logs for errors
- Try increasing `NALLY_MAX_AGENT_WALL_TIME` in `.env`

### "Unauthorized" (401)
- Your Bearer token doesn't match `NALLY_ACCESS_TOKEN`
- Include header: `Authorization: Bearer <token>`

### SSE events not reaching frontend
- Check CORS: `ALLOWED_ORIGINS` must include your frontend URL
- Check browser console for connection errors
- Verify the `/api/chat` endpoint returns `text/event-stream` content type

## SSL / Proxy Issues

### "Streaming failed, falling back: [SSL: WRONG_VERSION_NUMBER]"
This error means the HTTPS connection to your LLM provider is being intercepted. Usually caused by:
- Corporate/school proxy or firewall
- Antivirus with SSL scanning (Kaspersky, ESET, etc.)
- ISP-level traffic inspection

**Fix — Option 1:** Connect from a different network (mobile hotspot) to confirm it's network-related.

**Fix — Option 2:** Configure a proxy in `.env`:
```env
HTTPS_PROXY=http://proxy.company.com:8080
HTTP_PROXY=http://proxy.company.com:8080
```

**Fix — Option 3:** If you have a self-signed certificate or custom CA:
```env
NALLY_CA_BUNDLE=/path/to/ca-bundle.crt
```

**Fix — Option 4:** Disable SSL verification (not recommended for production):
```env
NALLY_VERIFY_SSL=false
```

Note: Even when streaming fails, Nally falls back to non-streaming — you'll still get responses, just without real-time text display.

## Voice Mode Not Working

### No audio input
- Check microphone permissions in your OS
- Verify `sounddevice` is installed: `pip install sounddevice`
- On Linux, ensure PulseAudio or ALSA is running

### STT not transcribing
- `faster-whisper` requires significant RAM (2-4GB)
- First run downloads the model (~150MB for base model)
- Check logs for CUDA errors if using GPU

### TTS not speaking
- **Piper**: Requires model download on first run. Check `data/piper/` directory exists
- **ElevenLabs**: Verify `ELEVENLABS_API_KEY` is set and valid

## Telegram Bot Issues

### Bot not responding
- Verify `TELEGRAM_BOT_TOKEN` is set correctly
- Check if bot privacy mode is off (for group chats)
- Bot only responds to @mentions in groups

### Voice messages not working
- Requires `ffmpeg` installed and in PATH
- Check `nally/telegram/voice.py` can find ffmpeg

### Polling vs Webhook
- Use polling for development: `python main.py --telegram`
- Use webhook for production (requires HTTPS URL)

## MCP Connection Issues

### "Failed to connect" errors
- Check the MCP server command/path is correct
- For HTTP servers, verify the URL is accessible
- For OAuth services, complete the OAuth flow via web UI

### OAuth token expired
- Disconnect and reconnect the service via `/api/mcp/disconnect/{service}`
- Re-initiate connection via `/api/mcp/connect/{service}`

### Tools not appearing after MCP connect
- Check server logs for tool registration errors
- Some MCP servers have noisy connection logs — this is suppressed by default

## Memory Issues

### Memories not persisting
- Check `data/nally.db` exists and is writable
- Verify WAL mode is enabled (default)
- Check disk space

### High memory usage
- The reflector runs hourly — disable by not starting it
- CLIP model for image scoring loads on first image generation
- Whisper model stays loaded for STT

## Image Generation

### "Pollinations API unreachable"
- Check internet connection
- Pollinations is a free service with no fallback
- Try again later if rate-limited

### Poor image quality
- Increase `max_attempts` parameter
- Use more descriptive prompts
- Try different content types (logo vs photo vs art)

## Performance

### Slow responses
- Reduce `NALLY_MAX_ITERATIONS` (default: 25)
- Reduce `NALLY_MAX_TOOL_CALLS` (default: 50)
- Use a faster model via `NALLY_PROVIDER` or `NALLY_THINKING_MODEL`
- Disable thinking: `NALLY_THINKING_ENABLED=false`

### Rate limiting yourself
- Default: 30 req/min, burst 60
- Adjust in `.env`: `RATE_LIMIT_RPM=60`, `RATE_LIMIT_BURST=120`
- Disable: `RATE_LIMIT_ENABLED=false`

## Getting Help

- Check server logs in `logs/` directory
- Run with debug logging: set logger level to DEBUG
- Check execution traces: `GET /api/traces` (shows recent runs)
