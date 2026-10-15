# N.A.L.L.Y Simplification Plan — All Phases

**Goal**: Reduce N.A.L.L.Y to a reliable, understandable core while preserving its best differentiators (permission gate, tool receipts, claim verifier, durable memory).

**Base**: `stableforABSU` @ `f7b4b211`

**Principles**
1. Keep only what is fully wired and proven on the main request path.
2. Quarantine (do not delete yet) anything with integration gaps.
3. Make the main request path short and obvious.
4. Preserve safety differentiators.
5. Result must still be useful day-to-day (chat + tools + memory + web/CLI).

---

## Phase 1 — Stabilize & Clean the Core

### 1.1 Fix CI blockers (this commit)

**A. Missing `import os` in bridge_handler.py**
- File: `nally/web/bridge_handler.py`
- Problem: `os.getenv("NALLY_BRIDGE_TOKEN", "")` used without import.
- Fix: added `import os`.

**B. RUF012 in tests/test_health.py**
- Problem: mutable class attribute `tools = {}` in nested `EmptyRegistry`.
- Fix: annotated with `ClassVar[dict]`.

### 1.2 Meaningful health checks (next)
- Current required tools: `run_command`, `read_file`, `file_ops`, `fetch`
- Consider adding `web_search` or documenting it as optional with clear status.

### 1.3 Clean main entry points
- Engineer mode currently bypasses `load_all_tools()`.
- Decision: move `--engineer` into quarantine / experimental in Phase 2.

---

## Phase 2 — Surgical Removal / Quarantine

Move the following into `attic/` (keep git history):

| Component | Path(s) | Reason |
|-----------|---------|--------|
| Autonomous engineering | `nally/engineering/` , `--engineer` in `main.py` | Not wired to core tools; calls unregistered `code_analysis`; auto-approves `ask` |
| Skills system | skills-related modules + `/api/skills` | Loader exists but not activated in agent system prompt / normal path |
| Advanced Voice / LiveKit | `nally/voice/livekit_*`, heavy audio deps | Incomplete verification + missing ffmpeg in Docker |
| Actor / group / SOP / personas | supporting modules not on main path | Dead weight for core |
| Unrestricted `/api/env/{key}` | web routes | Security risk — replace with allow-list |
| Broken `/orb` | route referencing missing `orb-standalone.html` | Dead code |

**Keep in core**
- LangGraph agent loop (`nally/agent/`)
- Core tools via `nally/tools/__init__.py`
- Permission gate + receipts + verifier
- Durable memory (SQLite primary)
- Web UI + basic API + CLI
- Config + OpenAI-compatible providers

---

## Phase 3 — Harden the Remaining Surface

1. Permissions consistency (no silent auto-approve of `ask` when no event callback)
2. Startup assert on required tools
3. Env endpoint allow-list
4. Minimal smoke / integration test
5. Enable coverage collection in CI
6. Docs match reality (README, DEPLOYMENT.md, API.md)

