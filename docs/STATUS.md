# Consolidation Status — `refactor/nally-architecture-consolidation`

Active hardening branch. `master` stays deployable; this branch lands
reviewed slices. Last updated: 2026-09-13.

## Phase tracker (P0 → P3)

| Phase | Scope | Status | Evidence |
|-------|-------|--------|----------|
| **P0 — Stabilize** | Controller + Planning Judge hardening; typed `AgentState` fields (`requires_approval`, `controller_tier`, `controller_max_steps`) | ✅ Done | `6170687`, `c17fd43` |
| **P1 — Context** | Typed Context Builder with tests | ✅ Done | `cc7c4a4` |
| **P2 — Verification** | Verification Facade consumption tests | ✅ Done | `b73dbc2` |
| **P3 — Memory authority** | Recall correctness, write discipline, context integration | ✅ Done | `abb10fc` |
| **P4 — Routing** | Capability Router + Sub-agent Boundary | ✅ Done | `991f13b` |
| **P5 — Budgets** | Deadline-authoritative `ExecutionBudget` (monotonic clock, warning ≠ completion); thread `max_tool_calls` / `max_failures` through state | ✅ Done | `38dd743`, `7b51f4a` |
| **Computer slices 1–4** | NallPuter models → orchestrator → reconnect/lifecycle → tool redirection through adapter | ✅ Done | `519009d`, `f3a764a`, `a5c65e4`, `d4c7cb5`, `142e86a` |
| **Benchmark** | Full-loop computer benchmark, 9/9 PASS baseline (`tests/eval/suite_u/REPORT.md`) | ✅ Done | `ab464f0` |

## What's next

- [ ] Merge `refactor/nally-architecture-consolidation` → `master` (squash or staged PRs per phase)
- [ ] Fix P0 audit items: missing `run_tg_user.py` / `run_tg_call.py` runners (Dockerfile + `main.py` reference them)
- [ ] Tighten `nally/config/permissions.json` catch-all (`run_command: "*": "allow"`, blanket `gmail_write` / `mcp_*` allow)
- [ ] Extract approval-gate DB + XML tool-call parsing out of `nally/agent/graph.py` (2,122 lines)
- [ ] Add tests for `nally/thinking/` (currently zero coverage)

## How to verify

```bash
ruff check . && ruff format --check .
python -m pytest tests/ -q
python -m tests.harness_eval.runner   # intent-classifier accuracy + latency
```

## Docs map

- Architecture: `docs/architecture/` (`ARCHITECTURE.md`, `HARNESS.md`, `COMPUTER.md`)
- Guides: `docs/guides/` (API, deployment, MCP, memory, skills, voice, frontend, testing, troubleshooting)
- Reference: `docs/reference/` (`CLAUDE.md` for AI assistants, personalities, plugins)
- Archive: `docs/archive/` (fix reports, release notes, research papers)
