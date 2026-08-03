# N.A.L.L.Y - AI Assistant

Personal AI assistant inspired by Jarvis from Iron Man. Built by Clinton (Klyntech/Klynvybz).

## Project Structure

```
N.A.L.L.Y/
├── main.py                 # Entry point (CLI, voice, web, telegram modes)
├── .env.example            # Template for environment variables
├── nally/
│   ├── config.py           # Single source of truth — all settings, no side effects
│   ├── config/
│   │   └── permissions.json # Tool permission rules (allow/ask/deny)
│   ├── core/
│   │   ├── errors.py       # Typed error hierarchy (NallyError, ToolError, LLMError, etc.)
│   │   └── validator.py    # Startup config validation, env var checks
│   ├── agent/
│   │   ├── core.py         # NallyAgent orchestrator (thread-safe lazy singleton)
│   │   ├── graph.py        # LangGraph state machine (ReAct loop, abort checkpoints)
│   │   ├── llm.py          # OpenAI-compatible LLM client (Groq/OpenCode)
│   │   ├── context.py      # Context management (compaction, memory injection)
│   │   ├── router.py       # Pattern matcher for instant local responses
│   │   └── sessions.py     # SessionManager — multi-session support, busy/queue logic
│   ├── tools/
│   │   ├── registry.py     # Tool registry + base Tool class
│   │   ├── permissions.py  # PermissionGate (allow/ask/deny per tool)
│   │   ├── filter.py       # Tool selection/filtering (core-only on weak match)
│   │   ├── system.py       # RunCommand, SystemHealth
│   │   ├── files.py        # ReadFile, FileOps
│   │   ├── code.py         # RunCode, CodeAnalysis
│   │   ├── imagegen.py     # Image generation (Pollinations API, CLIP scoring, critique loop)
│   │   ├── gmail.py        # Gmail direct tools (bypasses broken Google MCP)
│   │   ├── websearch.py    # Web search (Parallel.ai primary, DuckDuckGo fallback)
│   │   ├── mcp.py          # MCP status tool (shows server connection status)
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
│   ├── mcp/
│   │   ├── client.py       # MCP client — connects to MCP servers (stdio + HTTP/OAuth)
│   │   └── oauth.py        # OAuth 2.0 flow manager (DCR, PKCE, token encryption)
│   ├── db/
│   │   ├── postgres.py     # PostgreSQL adapter (asyncpg, Layerbase/self-hosted)
│   │   └── redis.py        # Redis cache (Layerbase REST or self-hosted redis-py)
│   ├── skills/
│   │   ├── loader.py       # Scans skills/*/SKILL.md, parses frontmatter, security validation
│   │   └── registry.py     # Skill registry singleton, hot-reload, intent matching
│   ├── telegram/
│   │   └── bot.py          # Telegram bot (DM + group chat, polling/webhook)
│   ├── voice/
│   │   ├── loop.py         # Voice interaction loop
│   │   ├── stt.py          # Speech-to-text
│   │   └── tts.py          # Text-to-speech
│   ├── web/
│   │   ├── app.py          # FastAPI server (SSE, rate limiting, CORS, OAuth callbacks)
│   │   ├── health.py       # Health endpoints (no auth — for Docker/k8s/load balancers)
│   │   └── ws_handler.py   # WebSocket bidirectional streaming
│   └── utils/
│       └── logger.py       # Structured logging
├── web/                    # Frontend (HTML/JS/CSS — Jarvis UI)
├── skills/                 # Skill definitions (skills/*/SKILL.md)
├── plugins/                # User plugins
├── data/                   # SQLite DB, user profile, todos, generated images
├── logs/                   # Application logs
└── requirements.txt
```

## Tech Stack

- **Backend**: Python, FastAPI, LangGraph, OpenAI SDK
- **Frontend**: Vanilla JS, HTML, CSS (no build tools)
- **LLM Providers**: OpenCode Zen (mimo-v2.5-free) or Groq (Llama 3.3)
- **Database**: SQLite (default), PostgreSQL via Layerbase or self-hosted, Redis for caching
- **Streaming**: Server-Sent Events (SSE) + WebSocket (bidirectional, lower latency)
- **MCP**: Model Context Protocol integrations (GitHub, Notion, Gmail, Drive, Calendar, Higgsfield, Telegram, Playwright, Context7, Meta)

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

# Layerbase (PostgreSQL + Redis)
LAYERBASE_API_KEY=sk_...         # Layerbase API key
LAYERBASE_DB_ID=...              # PostgreSQL database ID
REDIS_URL=redis://...            # Redis URL (Layerbase REST or self-hosted)
REDIS_TOKEN=...                  # Layerbase REST token

# Integrations
GOOGLE_CLIENT_ID=...             # Google OAuth client ID (Gmail/Drive/Calendar MCP)
GOOGLE_CLIENT_SECRET=...         # Google OAuth client secret
NALLY_CRED_KEY=...               # Fernet key for encrypting stored OAuth tokens
TELEGRAM_BOT_TOKEN=...           # Telegram bot token
PARALLEL_API_KEY=...             # Parallel.ai API key (web search)
META_ACCESS_TOKEN=...            # Meta Business Suite access token
```

## Key Architecture Decisions

- **No import-time side effects**: Config loads .env but doesn't create dirs or print warnings at import
- **Thread-safe singletons**: Agent, graph, memory all use double-checked locking
- **Typed errors**: All errors carry `code`, `message`, `severity`, `retryable` — no string matching
- **Permission gate**: `permissions.json` controls tool access (allow/ask/deny) — enforced at execution
- **Memory repository**: Connection-per-operation pattern (safe for multi-threaded FastAPI)
- **Backward compatibility**: `store_v2.py` shim preserves old imports during migration
- **MCP integrations**: External services (GitHub, Notion, Gmail, etc.) connected via MCP protocol with OAuth PKCE flows and encrypted token storage
- **Health endpoints skip auth**: `/health`, `/health/live`, `/health/ready` require no Bearer token — deliberate decision for Docker/k8s/load balancer probes, exposes no sensitive data
- **Image generation hard dependency**: Pollinations API (free, no key required) — the only tool with an external dependency besides the LLM provider itself; no fallback if API is down

## Code Style

- Python: Clean, no type hints required, follow existing patterns
- JS: Vanilla, no frameworks
- Personality: Nally talks casual, short, Lagos vibe
- Errors: Use typed errors from `nally/core/errors.py`, never bare `except: pass`
