# Changelog

All notable changes to N.A.L.L.Y will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Telegram Markdown→HTML formatter (`nally/telegram/format.py`) — bold, italic, code, headers, lists render properly in Telegram instead of showing raw markdown characters
- Telegram inline permission gates — Approve/Deny buttons for tool approval requests (run_command, git push), message disappears on click
- Shared abort module (`nally/core/abort.py`) — thread-safe `check_abort`/`set_abort`/`clear_abort` with Lock, fixes circular import between agent/graph.py and web/app.py
- MCP structured connection status — `connect_mcp_servers()` returns `[{name, status, tools, message}]` list instead of scattered log messages; status values: ok, awaiting, timeout, error
- MCP ExceptionGroup error cleanup — recursively unwraps inner errors from MCP SDK 1.29, shows clean messages like `ConnectError: ...` instead of `ExceptionGroup: unhandled errors in a TaskGroup (1 sub-exception)`
- MCP parse error suppression — `_connect_stdio_server()` temporarily sets `mcp.client.stdio` logger to CRITICAL during connection to suppress noisy "Failed to parse JSONRPC message" traceback
- Platform-aware system — OS/arch detection, auto shell selection (PowerShell on Windows, bash on Linux/macOS)
- Web search current-date injection — tool description includes today's date so the LLM searches with the correct year
- GitHub Actions CI pipeline — lint (ruff) + test (pytest) on push/PR to master
- GHCR publish workflow — Docker image publish on `v*` tags with semver + SHA tagging and GHA layer caching
- `.dockerignore` — build context exclusions for faster/smaller Docker builds
- Graph agent tests (`tests/test_graph.py`) — 12+ tests covering graph execution, retry logic, should_continue, doom loop detection

### Fixed

- Telegram formatting — agent returned raw Markdown (`**bold**`, `` `code` ``) but bot sent with `parse_mode="HTML"`, causing Telegram to reject and fall back to plain text; now converts Markdown to HTML before sending
- Telegram voice transcript HTML injection — user speech from voice messages is now HTML-escaped before inserting into HTML response
- SSE `/api/events` infinite 401 loop — login now validates tokens against `/api/me` (auth-gated) instead of unauthenticated `/api/status`; SSE retries probe auth and re-shows login on invalid token instead of retrying forever
- Telegram bot crash on startup — `nonlocal BOT_USERNAME` changed to `global` (module-level variable, not closure)
- `.gitignore` was tracking `.dockerignore` — removed the offending line so `.dockerignore` is now committed
- MCP SDK 1.26 incompatibility — upgraded to 1.29.0 which pulls anyio 4.14.2, fixing `TypeError: 'function' object is not subscriptable` on every MCP server connection
- Deprecated `streamablehttp_client` API replaced with `streamable_http_client` (new API takes `httpx.AsyncClient` instead of raw headers)
- Module-scope side effect — `_gen_dir.mkdir()` moved from module scope into `lifespan()` startup
- Shutdown crash — changed `agent.clear_history()` to `agent._save_history()` in lifespan shutdown
- Startup log noise — suppressed `nally.mcp`, `nally.tools`, `nally.memory`, `nally.skills`, `mcp`, `telegram`, `httpx`, `httpcore` loggers during startup display, restored after tree printed

### Changed

- Nally personality shifted to first-person POV — removed third-person self-references
- Startup banner rewritten — pyfiglet `block` font with rich iris purple (`#7C6AEF`) styling
- Startup display — rich tree-style showing config status, tool count, MCP server statuses, agent pre-warm, reflector status
- Voice toggle removed from text input — text messages always respond with text; voice toggle (`/voice`) only affects voice input
- `load_all_tools()` returns `(tool_count, mcp_status)` tuple instead of just count
- Config validation dedup — removed duplicate validation from `main.py`, only `lifespan()` validates now
- FastAPI upgraded to 0.141.1 (from 0.104.1) for starlette 1.4.1 compatibility
- MCP SDK upgraded to 1.29.0 (from 1.26.0), anyio 4.14.2 added
- `rich>=13.0` and `pyfiglet>=1.0` added to requirements

## [1.0.0] - 2026-01-01

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
- Layerbase/PostgreSQL + Redis database adapters

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
- Video editing, UI design, test writing, shipping, research, refactoring, design-system, productivity, creative, code-review, plan, image generation, docs, diagnose, devops, API design, architect, backend API skills
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
