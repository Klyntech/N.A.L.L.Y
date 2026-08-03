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
- **MCP Integrations** — Connect to GitHub, Notion, Gmail, Google Drive, Calendar, Higgsfield, Playwright, and more via Model Context Protocol
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
| Database | SQLite (default), PostgreSQL, Redis |
| Streaming | SSE + WebSocket |
| MCP | GitHub, Notion, Gmail, Drive, Calendar, Higgsfield, Telegram, Playwright, Context7, Meta |

## Project Structure

```
nally/
├── config.py           # All settings (single source of truth)
├── core/
│   ├── errors.py       # Typed error hierarchy
│   └── validator.py    # Startup config validation
├── agent/              # Agent orchestrator + LangGraph
├── tools/              # Tool registry + implementations
│   ├── system.py       # RunCommand, SystemHealth
│   ├── files.py        # ReadFile, FileOps
│   ├── code.py         # RunCode, CodeAnalysis
│   ├── imagegen.py     # Image generation (Pollinations)
│   ├── gmail.py        # Gmail direct API tools
│   ├── websearch.py    # Web search (Parallel.ai + DuckDuckGo)
│   └── mcp.py          # MCP server status
├── memory/             # Memory repository + models
├── subagent/           # Sub-agent spawning
├── mcp/                # MCP client + OAuth flows
├── db/                 # PostgreSQL + Redis adapters
├── skills/             # Skill loading system
├── telegram/           # Telegram bot
├── voice/              # Voice interaction (STT/TTS)
├── web/
│   ├── app.py          # FastAPI server
│   ├── health.py       # Health endpoints (no auth)
│   └── ws_handler.py   # WebSocket streaming
└── utils/logger.py     # Structured logging
```

## Development

```bash
# Run in CLI mode
python main.py --cli

# Run with specific provider
python main.py --provider groq

# Run on custom port
python main.py --port 8080
```

## License

Private — Built by Clinton Onyedikachi Chukwuma (Klyntech)
