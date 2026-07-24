# N.A.L.L.Y - AI Assistant

Personal AI assistant inspired by Jarvis from Iron Man. Built by Clinton (Klyntech/Klynvybz).

## Project Structure

```
N.A.L.L.Y/
├── main.py                 # Entry point (CLI, voice, web modes)
├── nally/
│   ├── config.py           # Single source of truth — all settings, no side effects
│   ├── core/
│   │   └── errors.py       # Typed error hierarchy (NallyError, ToolError, LLMError, etc.)
│   ├── agent/
│   │   ├── core.py         # NallyAgent orchestrator (thread-safe lazy singleton)
│   │   ├── graph.py        # LangGraph state machine (ReAct loop)
│   │   ├── llm.py          # OpenAI-compatible LLM client (Groq/OpenCode)
│   │   ├── context.py      # Context management (compaction, memory injection)
│   │   └── router.py       # Pattern matcher for instant local responses
│   ├── tools/
│   │   ├── registry.py     # Tool registry + base Tool class
│   │   ├── permissions.py  # PermissionGate (allow/ask/deny per tool)
│   │   ├── filter.py       # Tool selection/filtering for queries
│   │   ├── system.py       # RunCommand, SystemHealth
│   │   ├── files.py        # ReadFile, FileOps
│   │   ├── code.py         # RunCode, CodeAnalysis
│   │   └── __init__.py     # load_all_tools() — registers everything
│   ├── memory/
│   │   ├── store.py        # MemoryRepository (thread-safe, connection-per-op)
│   │   ├── models.py       # Data classes: Memory, Episode, ConversationSummary
│   │   ├── confidence.py   # Pure functions: decay, boost, days_since
│   │   ├── store_v2.py     # Backward-compat shim (deprecated, use store.py)
│   │   └── __init__.py     # Exports memory_store singleton
│   ├── subagent/
│   │   ├── agent.py        # SubAgent — autonomous sub-agent with own LLM session
│   │   ├── pool.py         # SubAgentPool — thread-safe spawn/manage/collect
│   │   ├── decomposer.py   # TaskDecomposer — breaks goals into parallel subtasks
│   │   └── tools.py        # Agent tool (delegate/spawn/collect/status)
│   ├── web/
│   │   └── app.py          # FastAPI server (SSE streaming, rate limiting, CORS)
│   └── utils/
│       └── logger.py       # Structured logging
├── web/                    # Frontend (HTML/JS/CSS — Jarvis UI)
├── plugins/                # User plugins
├── data/                   # SQLite DB, user profile, todos
├── logs/                   # Application logs
└── requirements.txt
```

## Tech Stack

- **Backend**: Python, FastAPI, LangGraph, OpenAI SDK
- **Frontend**: Vanilla JS, HTML, CSS (no build tools)
- **LLM Providers**: OpenCode Zen (mimo-v2.5-free) or Groq (Llama 3.3)
- **Database**: SQLite (langgraph-checkpoint-sqlite + memory repository)
- **Streaming**: Server-Sent Events (SSE)

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run web server (default port 5000)
python main.py

# Run CLI mode
python main.py --cli

# Run with specific provider
python main.py --provider groq
python main.py --provider opencode

# Run on custom port
python main.py --port 8080
```

## Environment Variables (.env)

```env
# Required
NALLY_PROVIDER=opencode          # or "groq"
OPENCODE_API_KEY=sk-...          # OpenCode Zen API key
GROQ_API_KEY=gsk_...             # Groq API key (if using groq)
NALLY_ACCESS_TOKEN=your-secret   # Auth token for API access

# Optional
NALLY_SESSION=default            # Session ID for persistence
NALLY_PERSONALITY=nally          # Active personality
ALLOWED_ORIGINS=http://localhost:5000  # CORS origins (comma-separated)
RATE_LIMIT_ENABLED=true          # Enable rate limiting
RATE_LIMIT_RPM=30                # Requests per minute per IP
RATE_LIMIT_BURST=5               # Burst capacity
DATABASE_URL=data/nally.db       # SQLite/Turso database path
TURSO_URL=libsql://...           # Turso cloud database URL
TURSO_TOKEN=...                  # Turso auth token
```

## Key Architecture Decisions

- **No import-time side effects**: Config loads .env but doesn't create dirs or print warnings at import
- **Thread-safe singletons**: Agent, graph, memory all use double-checked locking
- **Typed errors**: All errors carry `code`, `message`, `severity`, `retryable` — no string matching
- **Permission gate**: `permissions.json` controls tool access (allow/ask/deny) — enforced at execution
- **Memory repository**: Connection-per-operation pattern (safe for multi-threaded FastAPI)
- **Backward compatibility**: `store_v2.py` shim preserves old imports during migration

## Code Style

- Python: Clean, no type hints required, follow existing patterns
- JS: Vanilla, no frameworks
- Personality: Nally talks casual, short, Lagos vibe
- Errors: Use typed errors from `nally/core/errors.py`, never bare `except: pass`
