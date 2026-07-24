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

- **Chat** — Talk to Nally via web UI or CLI
- **Tools** — Run commands, read/write files, analyze code, control system
- **Memory** — Remembers facts, episodes, and conversation history across sessions
- **Sub-agents** — Spawn parallel sub-agents for complex tasks
- **Streaming** — Real-time SSE streaming for responsive feel

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
| Database | SQLite |
| Streaming | Server-Sent Events (SSE) |

## Project Structure

```
nally/
├── config.py           # All settings (single source of truth)
├── core/errors.py      # Typed error hierarchy
├── agent/              # Agent orchestrator + LangGraph
├── tools/              # Tool registry + implementations
├── memory/             # Memory repository + models
├── subagent/           # Sub-agent spawning
├── web/app.py          # FastAPI server
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
