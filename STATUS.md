# N.A.L.L.Y Simplification STATUS

**Branch**: simplify/phase1-ci-fixes (from stableforABSU @ f7b4b211)
**Started**: 2026-10-15

## Phase 1 — Stabilize & Clean the Core

| Item | Status | Notes |
|------|--------|-------|
| Fix missing `import os` in `nally/web/bridge_handler.py` | ✅ Done | This commit |
| Fix RUF012 in `tests/test_health.py` | ✅ Done | ClassVar annotation |
| Make health checks require `web_search` (or document optional) | 🔲 TODO | |
| Ensure engineer path either loads tools or is gated | 🔲 TODO | Phase 2 |
| Green CI on the two known failures | 🔲 Pending push | |

## Phase 2 — Surgical Removal / Quarantine

| Item | Status | Notes |
|------|--------|-------|
| Create `attic/` directory | 🔲 | |
| Move `nally/engineering/` → attic | 🔲 | |
| Gate or remove `--engineer` from main.py | 🔲 | |
| Quarantine skills / advanced voice / etc. | 🔲 | |
| Restrict unrestricted `/api/env` | 🔲 | |
| Remove broken `/orb` route | 🔲 | |
| Update imports & docs after moves | 🔲 | |

## Phase 3 — Harden Remaining Surface

| Item | Status | Notes |
|------|--------|-------|
| Consistent permissions (no silent auto-approve of ask) | 🔲 | |
| Startup assert on required tools | 🔲 | |
| Env endpoint allow-list | 🔲 | |
| Minimal smoke / integration test | 🔲 | |
| Enable coverage in CI | 🔲 | |
| Docs match reality | 🔲 | |
