# N.A.L.L.Y

Personal AI assistant inspired by Jarvis from Iron Man. Built by Clinton (Klyntech/Klynvybz).

## Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Set up environment
cp .env.example .env
# Edit .env with your API keys

# 3. Run
python main.py
```

Then open http://localhost:5000 in your browser.

## What It Does

- **Chat** — Talk to Nally via web UI, CLI, or Telegram bot
- **Tools** — Run commands, read/write files, analyze code, control system, generate images
- **Memory** — Remembers facts, episodes, and conversation history across sessions
- **MCP Integrations** — GitHub, Notion, Gmail via Model Context Protocol; Google Drive/Calendar + Higgsfield via OAuth flows
- **Sub-agents** — Spawn parallel sub-agents for complex tasks
- **Streaming** — Real-time SSE and WebSocket streaming for responsive feel

## Configuration

All settings live in `.env`:

```env
NALLY_PROVIDER=opencode          # or "groq"
OPENCODE_API_KEY=sk-...          # OpenCode Zen API key
GROQ_API_KEY=gsk_...             # Groq API key (if using groq)
NALLY_ACCESS_TOKEN=your-secret   # Auth token for API access
```

See [CLAUDE.md](CLAUDE.md) for full configuration reference.

## Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md) for system design, patterns, and data flow.

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | Python, FastAPI, LangGraph |
| Frontend | Vanilla JS, HTML, CSS |
| LLM | OpenCode Zen or Groq |
| Database | SQLite (`data/nally.db` + `data/nally_memory.db`); PostgreSQL/Redis reachability health probes only |
| Streaming | SSE + WebSocket |
| MCP | GitHub, Notion, Gmail (default servers); Google Drive/Calendar + Higgsfield via OAuth; Context7/Meta/Telegram via npm packages |

## Project Structure

```
nally/
├── config.py           # All settings (single source of truth)
├── core/
│   ├── errors.py       # Typed error hierarchy
│   ├── startup.py      # StartupDisplay + print_banner
│   └── validator.py    # Startup config validation
├── agent/              # Agent orchestrator + LangGraph (incl. harness, scratchpad)
├── tools/              # Tool registry + implementations
│   ├── system.py       # RunCommand, SystemHealth
│   ├── files.py        # ReadFile, FileOps
│   ├── code.py         # RunCode, CodeAnalysis
│   ├── imagegen.py     # Image generation (Pollinations)
│   ├── gmail.py        # Gmail direct API tools
│   ├── websearch.py    # Web search (Parallel.ai + DuckDuckGo)
│   ├── fetch.py        # Web page fetch tool
│   ├── phone.py        # Plivo telephony tool
│   └── mcp.py          # MCP server status
├── memory/             # Memory repository + models
├── subagent/           # Sub-agent spawning
├── engineering/        # Autonomous engineering loop (python main.py --engineer)
├── curiosity/          # Proactive idle-cycle learning (feeds, interests, scanner)
├── mcp/                # MCP client + OAuth flows
├── skills/             # Skill loading system
├── telegram/           # Telegram bot (+ user.py Telethon, voice_call.py)
├── voice/              # Voice interaction (STT/TTS, pipeline, metrics, LiveKit)
├── web/
│   ├── app.py          # FastAPI server
│   ├── health.py       # Health endpoints (no auth; DB/Redis probes)
│   └── ws_handler.py   # WebSocket streaming
└── utils/logger.py     # Structured logging
```

## Development

```bash
# Run in CLI mode
python main.py --cli

# Run voice mode (push-to-talk)
python main.py --voice

# Run the web server (default; Telegram bot auto-spawns in polling mode)
python main.py

# Run the Telegram bot only (no web server)
python main.py --telegram-only

# Run the Telegram bot in a separate process (polling mode)
python run_bot_standalone.py

# Run the Telethon user-account client (real user, separate process)
python run_tg_user.py

# Run Telegram voice-call sessions (pytgcalls, separate process)
python run_tg_call.py

# Run the autonomous engineering loop on a task
python main.py --engineer "TASK"
python -m nally.engineering

# Run with specific provider
python main.py --provider groq
python main.py --provider opencode

# Show full MCP server tree during startup
python main.py --verbose

# Run on custom port
python main.py --port 8080

# Evaluate the Harness intent classifier against test cases
python -m tests.harness_eval.runner
```

## VoIP / Live Voice (Phone Calls)

Zero-cost phone interface — dial Nally from a free SIP app (e.g. Linphone) via a LiveKit Cloud SIP Inbound Trunk. Requires LiveKit Cloud credentials and an inbound trunk (see `docs/LIVEKIT_SIP_SETUP.md`):

```bash
pip install -r requirements.txt
python -m nally.voice.livekit_agent
```

## License

Private — Built by Clinton Onyedikachi Chukwuma (Klyntech)
