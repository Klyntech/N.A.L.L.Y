# Changelog

All notable changes to N.A.L.L.Y will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

### Changed

### Fixed

## [1.2.0] - 2026-08-13

### Added

- VoIP phone interface — zero-cost voice calls via LiveKit SIP Ingress (`nally/voice/livekit_agent.py`; set `NALLY_VOICE_CALLS_ENABLED` and run `python -m nally.voice.livekit_agent`); see `docs/LIVEKIT_SIP_SETUP.md`
- Telegram user account (`nally/telegram/user.py`, Telethon) with DM + proactive alert support — `run_tg_user.py`
- Telegram real-time voice calls (`nally/telegram/voice_call.py`, pytgcalls + Deepgram + Silero VAD + barge-in) — `run_tg_call.py`
- Structured tool success — `registry.execute()` returns `(result, success)`, the structured boolean being the primary signal for receipts, snapshot diffing, and frontend events; legacy `str(result).startswith("Error")` prefix check retained as defense-in-depth
- Receipt store rotation — JSONL auto-rotates at 10MB, keeps up to 5 rotated files, loads all on startup
- Telegram Markdown→HTML formatter (`nally/telegram/format.py`) — bold, italic, code, headers, lists, tables render properly
- Telegram inline permission gates — Approve/Deny buttons for tool approval requests
- Shared abort module (`nally/core/abort.py`) — thread-safe `check_abort`/`set_abort`/`clear_abort`
- MCP structured connection status (`connect_mcp_servers()` returns `[{name, status, tools, message}]`), ExceptionGroup cleanup, and parse-error suppression (SDK 1.29)
- Platform-aware system — OS/arch detection, auto shell selection (PowerShell on Windows, bash on Linux/macOS)
- Web search current-date injection so the LLM searches with the correct year
- GitHub Actions CI pipeline (ruff + pytest) and GHCR publish workflow with semver + SHA tagging and layer caching
- Harness evaluation runner — `python -m tests.harness_eval.runner` (intent-classifier accuracy + latency over `tests/harness_eval/cases/`)
- Full documentation overhaul — ARCHITECTURE, API, MCP_GUIDE, VOICE, MEMORY, SKILLS, PLUGINS, TESTING, FRONTEND, SECURITY, PERSONALITIES, DEPLOYMENT, and new HARNESS.md aligned with the actual codebase
- Missing runtime dependencies added to `requirements.txt` — `plivo` (phone tool), `pygetwindow` (window focus), `readability-lxml` (fetch tool), `torch` (voice-pipeline VAD), `telethon` (user account), `pycaw`/`comtypes` (volume control)

### Changed

- Frontend modularized — monolithic `index.html` split into dedicated CSS/JS modules
- MCP SDK upgraded to 1.29.0 with the `streamable_http_client` API (replaces deprecated `streamablehttp_client`)
- Tool success detection — `registry.execute()` returns `tuple[str, bool]` instead of a bare string
- Telegram voice transcript HTML injection — user speech is HTML-escaped before inserting into HTML responses
- Nally personality shifted to first-person POV; startup banner rewritten (pyfiglet `block`, iris purple) with rich tree-style startup display
- `load_all_tools()` returns `(tool_count, mcp_status)` tuple; config validation deduplicated into `lifespan()`
- FastAPI upgraded to 0.141.1, `rich`/`pyfiglet` pinned; ruff format pass

### Fixed

- Audit hardening — tool-approval race condition, Telegram single-owner enforcement (`resolve_telegram_mode`), async safety, and credential/token scrubbing
- Telegram bot startup crash, timeouts, approval buttons, and HTML formatting
- Issue #1 — permission rules, tool success detection, exception handling, and skills security validation
- Permission defaults — `file_ops` delete now `ask`; `think`, `web_search`, `mcp_status` explicitly `allow`; `rm -rf /`, `rm -rf ~`, `rm -rf *` remain `deny`; skill `allowed-tools` can no longer bypass explicit deny rules
- Intent-matching threshold raised 2→3 words; skill-name substring fallback removed
- SSE `/api/events` infinite 401 loop — login now validates against `/api/me`; SSE retries probe auth and re-shows login on invalid token
- Telegram bot startup crash — `nonlocal BOT_USERNAME` → `global`
- Module-scope side effect moved into `lifespan()`; shutdown crash fix; startup log-noise suppression
- MCP SDK 1.26 incompatibility fixed by 1.29.0 (anyio 4.14.2); `.dockerignore` now committed

## [1.1.0]

### Added

- Execution tracing — nested span-based run trees persisted to SQLite (`nally/core/tracing.py`)
- Tool receipts — HMAC-signed, tamper-evident audit trail (`nally/tools/receipts.py`)
- Claim verifier — cross-checks LLM claims against tool receipts (`nally/agent/verifier.py`)
- Plan-and-Execute pipeline with agent safety (`nally/agent/planner.py`)
- Background reflector — hourly LLM-powered summarization
- Telegram Markdown→HTML formatter
- SSE auth fix and version-bump infrastructure
- Harness v2, scratchpad, thinking engine, curiosity, and engineering modules introduced

### Changed

- Platform-aware system prompts; interface awareness; voice formatter wiring
- Telegram voice support groundwork

### Fixed

- Startup validation and tool-approval flow refinements

## [1.0.0] - 2026-07-22

### Added — Architecture

- Backend redesign: typed error hierarchy (`NallyError`, `ToolError`, `LLMError`), memory repository with connection-per-operation pattern, permission gate (allow/ask/deny per tool), clean architecture throughout
- Holographic glitch cinema frontend (WebGL + Canvas 2D fallback, typewriter reveal, ambient cursor particles)

### Added — Agent & Core

- LangGraph ReAct-style agent with abort checkpoints (stop agent mid-operation)
- Plan-and-execute pipeline with agent safety (wall clock budget, doom loop detection, fresh thread per invocation)
- Decoupled event bus for pub/sub communication across agent components
- Sub-agent pool with autonomous spawning, task decomposition, and model override
- Claim verifier — LLM-powered fact checking of agent claims
- Circuit breaker pattern — summarizes findings via final LLM call instead of hardcoded string
- Context management: compaction, pruning, overflow detection with lower thresholds
- Iteration/tool-call limits centralized in config (100 each)
- Message queue + busy response for concurrent session handling

### Added — MCP & Integrations

- MCP client — connect to external MCP servers (stdio + HTTP), wrap tools into Nally registry
- MCP OAuth: GitHub, Notion (OAuth + PKCE), Google (OAuth + PKCE), Higgsfield (video generation)
- Direct Gmail tools (bypasses broken Google MCP)
- MCP services panel: service icons, token storage, PAT token flow
- Telegram bot with unified sessions — DM + group chat support
- PostgreSQL/Redis reachability health probes

### Added — Tools

- Image generation: Pollinations API (free, no key), smart model router, LLM prompt enhancement, 8-metric CLIP scoring, critique loop
- Web search (Parallel.ai primary, DuckDuckGo fallback) with freshness injection for time-sensitive queries
- Tool filtering — core-only on generic/empty queries
- Permission gate with configurable allow/ask/deny rules per tool
- Diff preview in approval flow + memory_stats tool
- Git command auto-allow for safe operations
- Tool receipts for tracking tool execution results
- Plugin system: allowlist-gated loading, permission validation

### Added — Voice & UX

- Push-to-talk voice I/O layer (Phase 1) with STT/TTS
- Background reflector for voice interactions
- Frontend redesign: cosmic dust cinema engine, services panel, login gate

### Added — Skills & Training

- Skill system — `skills/*/SKILL.md` with frontmatter parsing and hot-reload
- Video editing, UI design, test writing, shipping, research, refactoring, design-system, productivity, creative, code-review, plan, image generation, docs, diagnose, devops, API design, architect, backend API, build, data skills
- Training: 8 frontend quality lessons, backend quality rules, anti-hallucination safeguards

### Added — Infrastructure

- Dockerfile with non-root user and health checks
- `requirements.txt` and `pyproject.toml` build metadata
- `.env.example` with all config variables documented
- Structured logging module
- Startup config validation

### Fixed

- Duplicate responses (stream_done race condition)
- SystemMessage crash on empty tool calls
- `asyncio.run` in event loop (async context)
- MCP stdio server env var injection
- UnicodeDecodeError in subprocess calls (UTF-8 encoding)
- Token leak in `/api/config` (removed unauthenticated endpoint)
- Context overflow — tool filtering, pruning, lower thresholds
- `loadHistory` timing — `waitForMarked` helper ensures `marked.js` is loaded before use
- Anti-hallucination: gate skill injection on creation-request detection, clear cache on miss
- `marked@4.3.0` pinned to fix `[object Object]undefined` in table rendering

### Changed

- Requirements trimmed — removed unnecessary dependencies
- Auth timing fix (constant-time comparison via `hmac.compare_contents`)
- Ruff format pass across entire codebase