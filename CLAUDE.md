# N.A.L.L.Y - AI Assistant

**Version**: 1.2.0

Personal AI assistant inspired by Jarvis from Iron Man. Built by Clinton (Klyntech/Klynvybz).

## Project Structure

```
N.A.L.L.Y/
├── main.py                 # Entry point (CLI, voice, web, telegram modes)
├── run_bot_standalone.py   # Telegram bot in a separate process (polling mode)
├── run_tg_user.py          # Telethon real-user account (separate process)
├── run_tg_call.py          # Telegram voice-call sessions via pytgcalls (separate process)
├── .env.example            # Template for environment variables
├── nally/
│   ├── config.py           # Single source of truth — all settings, no side effects
│   ├── config/
│   │   └── permissions.json # Tool permission rules (allow/ask/deny)
│   ├── core/
│   │   ├── errors.py       # Typed error hierarchy (NallyError, ToolError, LLMError, PlanError, etc.)
│   │   ├── validator.py    # Startup config validation, env var checks
│   │   ├── startup.py      # StartupDisplay + print_banner
│   │   ├── abort.py        # Thread-safe abort flags (shared between agent/graph and web)
│   │   └── tracing.py      # Execution tracer — nested spans, run trees, SQLite persistence
│   ├── agent/
│   │   ├── core.py         # NallyAgent orchestrator (thread-safe lazy singleton)
│   │   ├── graph.py        # LangGraph state machine (ReAct loop, abort checkpoints)
│   │   ├── llm.py          # OpenAI-compatible LLM client (Groq/OpenCode)
│   │   ├── context.py      # Context management (compaction, memory injection)
│   │   ├── router.py       # Pattern matcher for instant local responses
│   │   ├── sessions.py     # SessionManager — multi-session support, busy/queue logic
│   │   ├── planner.py      # Plan-and-Execute pipeline (classify→plan→execute→replan→synthesize)
│   │   ├── platform.py     # OS/shell detection, auto-injected into system prompt
│   │   ├── verifier.py     # Claim verifier — cross-checks LLM claims against tool receipts
│   │   ├── harness.py      # Harness v2 — intent classification, pipeline routing, critique, tool verify
│   │   └── scratchpad.py   # Per-request working memory (ephemeral, separate from long-term memory)
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
│   │   ├── fetch.py        # Web page fetch tool
│   │   ├── phone.py        # Plivo telephony tool (PLIVO_* env vars)
│   │   ├── mcp.py          # MCP status tool (shows server connection status)
│   │   ├── receipts.py     # HMAC-signed tool execution receipts (tamper-evident audit trail)
│   │   └── __init__.py     # load_all_tools() — registers everything
│   ├── memory/
│   │   ├── store.py        # MemoryRepository (thread-safe, connection-per-op)
│   │   ├── models.py       # Data classes: Memory, Episode, ConversationSummary, SemanticPattern
│   │   ├── confidence.py   # Pure functions: decay, boost, days_since
│   │   ├── store_v2.py     # Backward-compat shim (deprecated, use store.py)
│   │   ├── reflector.py    # Background reflection engine (hourly LLM-powered summarization)
│   │   └── __init__.py     # Exports memory_store singleton
│   ├── subagent/
│   │   ├── agent.py        # SubAgent — autonomous sub-agent with own LLM session
│   │   ├── pool.py         # SubAgentPool — thread-safe spawn/manage/collect
│   │   ├── decomposer.py   # TaskDecomposer — breaks goals into parallel subtasks
│   │   └── tools.py        # Agent tool (delegate/spawn/collect/status)
│   ├── mcp/
│   │   ├── client.py       # MCP client — connects to MCP servers (stdio + HTTP/OAuth)
│   │   └── oauth.py        # OAuth 2.0 flow manager (DCR, PKCE, token encryption)
│   ├── engineering/        # Autonomous engineering loop (run via python -m nally.engineering)
│   ├── curiosity/          # Proactive idle-cycle learning (feeds.py, interests.py, scanner.py)
│   ├── skills/
│   │   ├── loader.py       # Scans skills/*/SKILL.md, parses frontmatter, security validation
│   │   └── registry.py     # Skill registry singleton, hot-reload, intent matching
│   ├── telegram/
│   │   ├── bot.py          # Telegram bot (DM + group chat, polling/webhook)
│   │   ├── user.py         # Telethon real-user account (launched via run_tg_user.py)
│   │   ├── voice_call.py   # Telegram voice-call sessions via pytgcalls (run_tg_call.py)
│   │   ├── format.py       # Markdown→Telegram HTML converter
│   │   └── voice.py        # OGG/PCM/WAV audio conversion for Telegram voice
│   ├── voice/
│   │   ├── loop.py         # Voice interaction loop
│   │   ├── stt.py          # Speech-to-text (Groq Whisper-first, faster-whisper fallback, Deepgram streaming)
│   │   ├── tts.py          # Text-to-speech (Piper / ElevenLabs / Fish Audio)
│   │   ├── formatter.py    # Text→speech formatting
│   │   ├── pipeline.py     # VoicePipeline streaming orchestrator
│   │   ├── metrics.py      # OpenTelemetry/Prometheus metrics
│   │   ├── bargein.py      # Barge-in detector (barge_in.py is legacy/unused)
│   │   ├── livekit_agent.py # LiveKit VoIP agent
│   │   └── speech_pipeline.py # End-to-end speech pipeline
│   ├── thinking/           # Thinking/reasoning module
│   │   ├── tool.py          # ThinkTool — structured reasoning before complex tasks
│   │   ├── engine.py        # ThinkingEngine — multi-strategy reasoning orchestrator
│   │   ├── config.py        # Thinking-specific config (model, timeout, strategies)
│   │   ├── prompts.py       # System prompts for thinking strategies
│   │   └── strategies.py    # Strategy registry — domain-specific reasoning approaches
│   ├── events/             # Pub/sub event bus
│   │   └── bus.py          # Event bus for plan events and agent notifications
│   ├── web/
│   │   ├── app.py          # FastAPI server (SSE, rate limiting, CORS, OAuth callbacks)
│   │   ├── health.py       # Health endpoints (no auth — for Docker/k8s/load balancers)
│   │   └── ws_handler.py   # WebSocket bidirectional streaming
│   └── utils/
│       └── logger.py       # Structured logging
├── web/                    # Frontend (HTML/JS/CSS — Jarvis UI; web/mvp/ = Three.js 3D avatar)
├── skills/                 # Skill definitions (skills/*/SKILL.md)
├── plugins/                # User plugins
├── tests/                  # Test suite (pytest — 29 test files: 28 in tests/ + tests/harness_eval/)
├── data/                   # SQLite DB (data/nally.db, data/nally_memory.db), user profile, todos, generated images (runtime, gitignored)
├── logs/                   # Application logs (runtime, gitignored)
├── Dockerfile              # Container image
├── docker-compose.yml      # Container orchestration
├── .github/workflows/      # CI (ci.yml) + publish (publish.yml) pipelines
└── requirements.txt
```

## Tech Stack

- **Backend**: Python, FastAPI, LangGraph, OpenAI SDK
- **Frontend**: Vanilla JS, HTML, CSS (no build tools)
- **LLM Providers**: OpenCode Zen (hy3-free) or Groq (Llama 3.3)
- **Database**: SQLite data store (`data/nally.db` + `data/nally_memory.db`); PostgreSQL/Redis exist only as reachability health probes (no adapter modules)
- **Streaming**: Server-Sent Events (SSE) + WebSocket (bidirectional, lower latency)
- **MCP**: GitHub, Notion, Gmail (default MCP servers); Google Drive/Calendar + Higgsfield via OAuth flows only; Context7/Meta/Telegram via npm packages — not default servers
- **TTS**: Piper (default) or ElevenLabs (`NALLY_TTS_BACKEND`) or Fish Audio (`FISH_*` env vars)
- **STT**: Groq Whisper API (first), faster-whisper (fallback), Deepgram streaming (real-time)
- **Image Gen**: Pollinations API (free, no key required)


## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run web server (default port 5000)
python main.py

# Run CLI mode
python main.py --cli

# Run voice mode (push-to-talk)
python main.py --voice

# Run Telegram bot only (no web server)
python main.py --telegram-only

# Run Telegram bot in a separate process (polling mode)
python run_bot_standalone.py

# Run the Telethon user-account client (real user, separate process)
python run_tg_user.py

# Run Telegram voice-call sessions (pytgcalls, separate process)
python run_tg_call.py

# VoIP phone interface (requires LiveKit Cloud — see docs/LIVEKIT_SIP_SETUP.md)
python -m nally.voice.livekit_agent

# Run the autonomous engineering loop (opt-in build mode)
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
RATE_LIMIT_BURST=60              # Burst capacity
DATABASE_URL=data/nally.db       # SQLite/Turso database path
TURSO_URL=libsql://...           # Turso cloud database URL
TURSO_TOKEN=...                  # Turso auth token

# Layerbase (PostgreSQL + Redis)
LAYERBASE_API_KEY=sk_...         # Layerbase API key
LAYERBASE_DB_ID=...              # PostgreSQL database ID
REDIS_URL=redis://...            # Redis URL (Layerbase REST or self-hosted)
REDIS_TOKEN=...                  # Layerbase REST token

# Integrations
GOOGLE_CREDENTIALS_FILE=...      # Path to Google credentials JSON (Gmail/Drive/Calendar MCP)
TELEGRAM_BOT_TOKEN=...           # Telegram bot token
PARALLEL_API_KEY=...             # Parallel.ai API key (web search)
SLACK_BOT_TOKEN=...              # Slack bot token
SLACK_WEBHOOK_URL=...            # Slack webhook URL
DISCORD_BOT_TOKEN=...            # Discord bot token
DISCORD_WEBHOOK_URL=...          # Discord webhook URL

# TTS (Text-to-Speech)
NALLY_TTS_BACKEND=piper          # "piper" (default), "elevenlabs", or "fish"
ELEVENLABS_API_KEY=...           # ElevenLabs API key (if using elevenlabs)
ELEVENLABS_VOICE_ID=...          # ElevenLabs voice ID (default: Rachel)
ELEVENLABS_MODEL=eleven_multilingual_v2  # ElevenLabs model
FISH_API_KEY=...                 # Fish Audio API key (if using fish backend)
FISH_VOICE_ID=...                # Fish Audio voice ID (empty = model default)
FISH_MODEL=s2.1-pro-free         # Fish Audio model

# STT (Speech-to-Text)
DEEPGRAM_API_KEY=...             # Deepgram API key (streaming/real-time STT)

# Proxy / SSL
HTTP_PROXY=...                   # HTTP proxy URL (e.g. http://proxy:8080)
HTTPS_PROXY=...                  # HTTPS proxy URL (e.g. http://proxy:8080)
NALLY_VERIFY_SSL=true            # Set to false to disable SSL verification
NALLY_CA_BUNDLE=...              # Path to custom CA bundle (e.g. /etc/ssl/certs/ca.crt)

# Agent Limits
NALLY_MAX_TOOL_CALLS=50          # Max tool calls per turn
NALLY_MAX_ITERATIONS=25          # Max LangGraph iterations per turn
NALLY_MAX_TOOL_OUTPUT=50000      # Tool output truncation limit (chars)
NALLY_MAX_AGENT_WALL_TIME=300    # Agent wall-clock budget (seconds)
NALLY_RECURSION_LIMIT=50         # LangGraph recursion limit
NALLY_APPROVAL_TIMEOUT=1800      # Tool approval timeout (seconds)

# Planning
NALLY_PLAN_ENABLED=false         # Enable Plan-and-Execute pipeline
NALLY_PLAN_MAX_STEPS=10          # Max plan steps
NALLY_PLAN_MAX_REVISIONS=3       # Max plan revisions on failure
NALLY_PLAN_STEP_TIMEOUT=300      # Per-step timeout (seconds)
NALLY_PLAN_STEP_MAX_ITERATIONS=15 # Per-step iteration limit

# Thinking
NALLY_THINKING_ENABLED=true      # Enable ThinkTool (structured reasoning)
NALLY_THINKING_MAX_STRATEGIES=3  # Max thinking strategies
NALLY_THINKING_MODEL=...         # Thinking-specific model (empty = default)
NALLY_THINKING_TIMEOUT=30        # Thinking timeout (seconds)
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
- **Tool receipts**: Every tool execution generates an HMAC-signed receipt stored in JSONL — tamper-evident audit trail used by the claim verifier to catch LLM hallucinations
- **Execution tracing**: Nested span-based tracing with parent-child relationships, run IDs, and thread-local span stacks — persisted to SQLite for debugging
- **Background reflector**: Hourly LLM-powered reflection that extracts summaries, episodes, and semantic patterns from recent conversations
- **Plan-and-Execute**: Optional pipeline (disabled by default) that classifies tasks, generates plans, executes steps via mini ReAct sub-loops, replans on failure, and synthesizes results
- **Claim verifier**: Post-response verification that cross-checks LLM claims against tool receipts — detects hallucinations without LLM in the hot path

## Code Style

- Python: Clean, no type hints required, follow existing patterns
- JS: Vanilla, no frameworks
- Personality: Nally talks casual, short, Lagos vibe
- Errors: Use typed errors from `nally/core/errors.py`, never bare `except: pass`
