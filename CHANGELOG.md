# Changelog

All notable changes to N.A.L.L.Y will be documented in this file.

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- Platform-aware system — OS/arch detection, auto shell selection (PowerShell on Windows, bash on Linux/macOS)
- Web search current-date injection — tool description includes today's date so the LLM searches with the correct year
- GitHub Actions CI pipeline — lint (ruff) + test (pytest) on push/PR to master
- GHCR publish workflow — Docker image publish on `v*` tags with semver + SHA tagging and GHA layer caching
- `.dockerignore` — build context exclusions for faster/smaller Docker builds

### Fixed

- SSE `/api/events` infinite 401 loop — login now validates tokens against `/api/me` (auth-gated) instead of unauthenticated `/api/status`; SSE retries probe auth and re-show login on invalid token instead of retrying forever
- Telegram bot crash on startup — `nonlocal BOT_USERNAME` changed to `global` (module-level variable, not closure)
- `.gitignore` was tracking `.dockerignore` — removed the offending line so `.dockerignore` is now committed

### Changed

- Nally personality shifted to first-person POV — removed third-person self-references

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
