# N.A.L.L.Y — Audit Fix Report

Date: 2026-08-13 · Applies to v1.1.0 codebase

## Security Warning (must act first)

> **The leaked Telegram bot token (`8889604268:...`) must be rotated immediately via BotFather.**
> Use `/revoke` then `/token` in BotFather to get a fresh token and update `.env`. Git history is
> intentionally **not** rewritten; the old token is still present in the git history of the deleted
> scratch files, so rotation is mandatory even though the working tree is clean.

## Summary

All CRITICAL and HIGH audit items are fixed, plus the MEDIUM/LOW hardening that was safe to apply
surgically. Full test suite passes (185 tests) and everything compiles.

Verification commands:
```bash
python -m compileall -q nally main.py run_bot_standalone.py
python -m pytest -q
```

## Files changed

### Modified
- `main.py` — spawns standalone bot only when Telegram mode == `polling`
- `run_bot_standalone.py` — exits cleanly unless mode == `polling`
- `nally/config.py` — `resolve_telegram_mode()`; lazy `SYSTEM_PROMPT`
- `nally/telegram/bot.py` — `_make_emit` return fix; `_callback_id_lock`; callable-arg guards
- `nally/web/app.py` — single-owner lifespan (webhook vs polling); `asyncio.to_thread` on approval paths
- `nally/web/health.py` — async DB/Redis checkers (no `asyncio.run` inside running loop)
- `nally/web/ws_handler.py` — `asyncio.to_thread` for approval resolution; removed dead `broadcast_all`
- `nally/agent/graph.py` — approval race fix (early-approval cache + TTL slack); `Event.wait` polling; `_RATE_LIMIT_RETRIES` used for no-model path
- `nally/agent/core.py` — `_thread_id` == `session_id` (abort key alignment); abort alias registration
- `nally/agent/llm.py` — removed dead router; model selection straight to active model
- `nally/agent/planner.py` — `shutdown(wait=False, cancel_futures=True)` in `_call_with_timeout`
- `nally/agent/sessions.py` — `_queue_lock`; atomic busy/queue/process/drain
- `nally/core/abort.py` — alias map (`register_alias`/`clear_alias`/`_resolve`)
- `nally/mcp/client.py` — `_run_coro_safely()` (no `asyncio.run` in running loop)
- `nally/tools/registry.py` — `ToolRegistry._lock`
- `nally/tools/__init__.py` — `_loaded_lock`; registration refactor
- `nally/tools/receipts.py` — `_lock` on shared dicts; store path anchored to `DATA_DIR`
- `nally/tools/websearch.py` — `_quota_lock` around check+increment; `threading` import
- `nally/tools/phone.py` — lazy `plivo` import (tool registry no longer breaks if plivo missing)
- `nally/events/bus.py` — `_stats`/`_history` reads and updates under lock
- `nally/memory/store.py` — removed dead `create_memory_store`; unused import pruned
- `nally/memory/confidence.py` — removed dead `initial_confidence`
- `nally/skills/loader.py` + `nally/skills/__init__.py` — removed dead `activate_skill`
- `nally/telegram/voice.py` — removed dead `pcm_to_ogg`
- `tests/test_graph.py` — corrected retry-count assertion to `_RATE_LIMIT_RETRIES`
- `.env.example` — added `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_URL`, `TELEGRAM_MODE`

### Deleted
- `check_db.py`, `test_ptb.py`, `test_parse.py`, `wsgi.py` (scratch files — source of the leaked token)
- `nally/db/__init__.py`, `nally/db/postgres.py`, `nally/db/redis.py` (zero external references; dead)

## Fixes by audit item

### CRITICAL
1. **Leaked Telegram bot token in repo** — deleted scratch files; verified no `.py` in working tree
   contains `8889604268:`; `.env.example` documents the variable. **Token still must be rotated.**
2. **`_make_emit` returns None → attribute error on `emit(...)`** — `return emit` moved to outer
   scope; call sites guard on callable.

### HIGH
3. **Dual Telegram owners (bot + webhook both polling)** — `resolve_telegram_mode()` returns
   `off`/`polling`/`webhook`; `main.py` spawns the bot subprocess only in polling mode; web lifespan
   starts Telegram only in webhook mode; `run_bot_standalone.py` exits unless polling.
4. **Approval race (resolve lands before gate persists pending)** — graph registers event +
   populates early result before persisting; `resolve_approval` caches early resolutions; TTL slack
   handles clock skew.
5. **Abort key mismatch (abort by `session_id` vs agent keyed by `nally-main-{sid}`)** — agent
   `_thread_id` now equals `session_id`; `run_agent` registers a `fresh_thread → thread_id` alias.
6. **Thread-pool starvation in approval gate** — replaced `time.sleep` polling with
   `approval_event.wait(_poll_interval)` (instant wake, no busy-spin); approval resolution runs via
   `asyncio.to_thread` in web/ws paths.

### MEDIUM
7. **`asyncio.run` inside a running loop** — `_check_database`/`_check_redis` made async and awaited;
   `_run_coro_safely()` in MCP client offloads to a fresh thread when a loop is already running.
8. **Thread-unsafe shared state** — locks added to bot callback-id map, session busy/queue, tool
   registry load, receipts store, websearch quota, event bus stats/history.
9. **Dead code** — removed `pcm_to_ogg`, `create_memory_store`, `initial_confidence`,
   `activate_skill`, `broadcast_all`, `nally/db` package, stale `NallyLLM` router.
10. **Receipt store path relative to CWD** — anchored to `DATA_DIR`.

### LOW
11. **Import-time side effects** — `SYSTEM_PROMPT` now lazy (no skills/platform probing at import).
12. **Hard dependency on `plivo`** — import deferred to call time; phone tools degrade gracefully.
13. **Stale test** — `test_no_model_uses_chat_with_retry` asserted `_MAX_RETRIES` while the
    no-model path correctly uses `_RATE_LIMIT_RETRIES`.

## Remaining risks (accepted / deferred)

- **Leaked token still in git history** — rotation is mandatory; history intentionally not rewritten.
- **Hardcoded values** — OAuth redirect URIs (`http://localhost:5000/...`) in
  `nally/mcp/oauth.py`, PowerShell binary path in `nally/agent/platform.py` &
  `nally/tools/system.py`, image-gen model names in `nally/tools/imagegen.py` are not yet moved to
  config/.env. Low impact (documented defaults, env-overridable only where noted).
- **Silent `except:` clauses** in `nally/agent/router.py` local-response handlers remain — they are
  intentional fallbacks, but a future audit may want explicit logging.
- **`nally/memory/models.py` kept** — still re-exported by `nally/memory/__init__.py`; the re-export
  can be removed in a follow-up if the public API is confirmed unused.
- **Layerbase vars** (`LAYERBASE_API_KEY`, `REDIS_URL`, etc.) remain documented in `.env.example`
  but the PostgreSQL/Redis adapters were removed; revisit if Layerbase is actually used.

## Safe run commands

```bash
# Web server only — no Telegram at all (must not run when polling bot is running)
python main.py                      # default: TELEGRAM_MODE=auto → off if no webhook URL/token set

# Telegram in webhook mode (web server owns bot; requires public HTTPS + TELEGRAM_WEBHOOK_URL)
python main.py

# Telegram in polling mode (standalone bot process + web server, single owner)
python main.py                      # TELEGRAM_MODE=polling → web server does NOT own the bot
# main.py auto-spawns run_bot_standalone.py in polling mode; or run it manually:
python run_bot_standalone.py

# CLI / voice (no Telegram)
python main.py --cli
python main.py --voice
```

Ownership rule enforced: **standalone bot process owns polling; web server owns webhook; never both
for the same token.**
