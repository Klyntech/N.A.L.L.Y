"""Nally Web Server - FastAPI backend with SSE streaming"""

import asyncio
import hmac
import json
import os
import sys
import time
import uuid
import webbrowser
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from nally.agent import get_agent
from nally.agent.sessions import session_manager
from nally.config import (
    ACTIVE_MODEL,
    ALLOWED_ORIGINS,
    DATA_DIR,
    PROVIDER,
    RATE_LIMIT_BURST,
    RATE_LIMIT_ENABLED,
    RATE_LIMIT_RPM,
    ensure_data_dir,
)
from nally.core.errors import NallyError
from nally.tools import load_all_tools
from nally.tools.registry import registry
from nally.utils.logger import logger

from .health import router as health_router

# ── Broadcast System (multi-tab sync) ─────────────────────


class _BroadcastManager:
    """Manages persistent SSE connections for real-time multi-tab sync."""

    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}
        self._counter = 0
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def subscribe(self) -> tuple[str, asyncio.Queue]:
        """Subscribe to broadcasts. Returns (client_id, queue)."""
        self._counter += 1
        cid = f"tab_{self._counter}"
        q: asyncio.Queue = asyncio.Queue()
        self._queues[cid] = q
        logger.info(f"SSE client connected: {cid} (total: {len(self._queues)})")
        return cid, q

    def unsubscribe(self, cid: str):
        self._queues.pop(cid, None)
        logger.info(f"SSE client disconnected: {cid} (total: {len(self._queues)})")

    def broadcast(self, event: str, data: dict):
        """Send an event to all connected SSE clients. Thread-safe."""
        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        dead = []
        for cid, q in self._queues.items():
            try:
                if self._loop and self._loop.is_running():
                    self._loop.call_soon_threadsafe(q.put_nowait, payload)
                else:
                    q.put_nowait(payload)
            except Exception:
                dead.append(cid)
        for cid in dead:
            self._queues.pop(cid, None)


broadcast_manager = _BroadcastManager()


# ── Paths ─────────────────────────────────────────────────

if getattr(sys, "frozen", False):
    _base = Path(sys.executable).parent
else:
    _base = Path(__file__).parent.parent.parent


# ── Auth ──────────────────────────────────────────────────

NALLY_ACCESS_TOKEN = os.environ.get("NALLY_ACCESS_TOKEN", "")
security = HTTPBearer(auto_error=False)


async def verify_auth(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if credentials and hmac.compare_digest(credentials.credentials, NALLY_ACCESS_TOKEN):
        return True
    raise HTTPException(status_code=401, detail="Unauthorized")


# ── Rate limiter (in-memory, per-IP) ─────────────────────


class _RateLimiter:
    """Simple token bucket rate limiter."""

    def __init__(self, rpm: int = 30, burst: int = 5):
        self._rpm = rpm
        self._burst = burst
        self._buckets: dict = {}
        self._last_refill = time.time()

    def _refill(self):
        now = time.time()
        elapsed = now - self._last_refill
        tokens_to_add = elapsed * (self._rpm / 60)
        for ip in list(self._buckets):
            self._buckets[ip] = min(self._burst, self._buckets[ip] + tokens_to_add)
        self._last_refill = now

    def allow(self, ip: str) -> bool:
        if not RATE_LIMIT_ENABLED:
            return True
        self._refill()
        if ip not in self._buckets:
            self._buckets[ip] = self._burst
        if self._buckets[ip] >= 1:
            self._buckets[ip] -= 1
            return True
        return False


_rate_limiter = _RateLimiter(rpm=RATE_LIMIT_RPM, burst=RATE_LIMIT_BURST)


# ── Request models ────────────────────────────────────────


class ChatRequest(BaseModel):
    message: str
    session_id: str = "web:default"
    tab_id: str = ""


class ApprovalRequest(BaseModel):
    tool_call_id: str
    approved: bool


# ── Lifespan ──────────────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    import logging
    import threading

    from rich.console import Console

    from nally.core.startup import StartupDisplay

    console = Console()
    display = StartupDisplay(console)

    # Suppress ALL noisy loggers during startup display
    _suppress = (
        "nally.mcp", "nally.tools", "nally.memory", "nally.skills",
        "mcp", "telegram", "httpx", "httpcore",
        "nally.memory.reflector",
        "uvicorn", "uvicorn.access", "uvicorn.error",
    )
    _saved_levels = {}
    for _name in _suppress:
        _l = logging.getLogger(_name)
        _saved_levels[_name] = _l.level
        _l.setLevel(logging.CRITICAL)

    ensure_data_dir()

    # Create generated images dir (moved from module scope)
    _gen_dir.mkdir(parents=True, exist_ok=True)

    # Validate config
    try:
        from nally.core.validator import validate_config

        errors = validate_config(strict=True)
        has_errors = any(e[0] == "error" for e in errors)
        if has_errors:
            for level, key, msg in errors:
                icon = "[red]ERROR[/]" if level == "error" else "[yellow]WARN[/]"
                console.print(f"  {icon}  {key}: {msg}")
            display.phase("Config", "[red]errors found[/]", ok=False)
        else:
            display.phase("Config", "[green]valid[/]")
    except Exception as e:
        display.phase("Config", f"[red]failed: {e}[/]", ok=False)
        raise

    # Load tools (includes MCP connections — now parallel)
    _tool_count, mcp_status = load_all_tools()

    display.phase("Tools", f"[green]{_tool_count} registered[/]")
    display.mcp_summary(mcp_status)

    # Pre-warm agent (threaded, non-blocking)
    agent_status = ["[yellow]starting...[/]"]
    reflector_status = ["[yellow]starting...[/]"]

    def _prewarm():
        try:
            get_agent()
            agent_status[0] = "[green]ready[/]"
        except Exception as e:
            agent_status[0] = f"[red]failed: {e}[/]"

    agent_thread = threading.Thread(target=_prewarm, daemon=True)
    agent_thread.start()

    # Start reflector
    try:
        from ..memory.reflector import reflector

        reflector.start(interval=3600)
        reflector_status[0] = "[green]active[/]"
    except Exception as e:
        reflector_status[0] = f"[red]failed: {e}[/]"

    # Wait for agent pre-warm (brief, don't block server)
    agent_thread.join(timeout=5)

    display.phase("Agent", agent_status[0])
    display.phase("Reflector", reflector_status[0])

    # Start Telegram bot — non-blocking via create_task
    # Single-owner enforcement (Path B): the standalone bot subprocess owns
    # polling; the web server only owns Telegram in webhook mode. In polling
    # mode we must NOT create any Application here — doing so would poll the
    # same token as the subprocess and cause Telegram 409 conflicts.
    _tg_status = "[dim]skipped[/]"
    app.state.telegram_app = None
    app.state._tg_task = None
    try:
        from ..config import resolve_telegram_mode

        telegram_mode = resolve_telegram_mode()

        if telegram_mode == "webhook":
            tg_webhook_url = os.getenv("TELEGRAM_WEBHOOK_URL", "").strip()

            async def _start_telegram_webhook_bg():
                """Background task: start Telegram webhook, capture the Application."""
                from ..telegram.bot import start_telegram_webhook
                tg_app = await start_telegram_webhook(tg_webhook_url)
                app.state.telegram_app = tg_app
                return tg_app

            app.state._tg_task = asyncio.create_task(_start_telegram_webhook_bg())
            _tg_status = "[green]connecting (webhook)...[/]"
        elif telegram_mode == "polling":
            _tg_status = "[green]running in separate process (polling)[/]"
        else:
            _tg_status = "[dim]off (TELEGRAM_MODE=off or no token)[/]"
    except Exception as e:
        _tg_status = f"[red]failed: {e}[/]"

    display.phase("Telegram", _tg_status)

    from nally.config import ACTIVE_MODEL, PROVIDER

    port = int(os.environ.get("PORT", "5000"))
    display.summary(port=port, provider=PROVIDER, model=ACTIVE_MODEL)

    # Restore logger levels for runtime
    for _name, _level in _saved_levels.items():
        logging.getLogger(_name).setLevel(_level)

    yield

    # Shutdown: stop reflector, telegram bot, and save all active sessions
    try:
        from ..memory.reflector import reflector

        reflector.stop()
    except Exception:
        pass
    try:
        tg_task = getattr(app.state, "_tg_task", None)
        tg_app = getattr(app.state, "telegram_app", None)

        # If bot is still starting up, cancel the task
        if tg_task and not tg_task.done():
            tg_task.cancel()
            try:
                await tg_task
            except asyncio.CancelledError:
                pass

        # If bot started successfully, stop it gracefully
        if tg_app:
            from ..telegram.bot import stop_telegram_polling
            await stop_telegram_polling(tg_app)
    except Exception:
        pass
    try:
        for _sid, agent in session_manager._sessions.items():
            if len(agent.messages) > 2:
                agent._save_history()
        logger.info("Saved all session summaries on shutdown.")
    except Exception as e:
        logger.warning(f"Shutdown save failed: {e}")
    logger.info("Lifespan shutdown.")


# ── App ───────────────────────────────────────────────────

app = FastAPI(title="Nally", lifespan=lifespan)

# CORS from config
_origins = (
    ALLOWED_ORIGINS
    if isinstance(ALLOWED_ORIGINS, list)
    else [o.strip() for o in ALLOWED_ORIGINS.split(",") if o.strip()]
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Health check (no auth required) ───────────────────────

app.include_router(health_router)


# ── Middleware: rate limit + request ID ───────────────────


@app.middleware("http")
async def _middleware(request: Request, call_next):
    # Rate limit — skip for static assets
    path = request.url.path
    if not path.startswith("/static/") and path != "/favicon.ico":
        client_ip = request.client.host if request.client else "unknown"
        if not _rate_limiter.allow(client_ip):
            return JSONResponse(
                status_code=429,
                content={"error": "rate_limit_exceeded", "message": "Too many requests. Please wait."},
            )

    # Request ID
    request_id = str(uuid.uuid4())[:8]
    request.state.request_id = request_id

    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


# ── Static files ──────────────────────────────────────────

_web_dir = _base / "web"
_data_dir = _base / "data"
_gen_dir = _data_dir / "generated"


@app.get("/")
async def index():
    return FileResponse(str(_web_dir / "index.html"))


# Serve JS/CSS assets from web/ directory
app.mount("/static", StaticFiles(directory=str(_web_dir)), name="static")

# Serve generated images
app.mount("/generated", StaticFiles(directory=str(_gen_dir)), name="generated")


@app.get("/web/")
async def web_root():
    return RedirectResponse(url="/", status_code=302)


# ── Debug page ────────────────────────────────────────────


@app.get("/debug")
async def debug_page():
    return """<!DOCTYPE html>
<html><head><title>Nally Debug</title>
<style>body{background:#0a0a0a;color:#0f0;font-family:monospace;padding:40px;font-size:14px;}
.log{margin:4px 0;padding:4px 8px;border-left:3px solid #333;}
.ok{border-color:#0f0;color:#0f0;}
.fail{border-color:#f00;color:#f00;}
.info{border-color:#0ff;color:#0ff;}</style>
</head><body>
<h2>Nally Debug Console</h2>
<div id="log"></div>
<script>
function L(cls, txt) {
  var d = document.createElement('div');
  d.className = 'log ' + cls;
  d.textContent = txt;
  document.getElementById('log').appendChild(d);
}
L('info', 'Server: FastAPI + SSE');
fetch('/api/status').then(r => r.json()).then(data => {
  L('ok', 'STATUS: ' + JSON.stringify(data));
}).catch(e => {
  L('fail', 'ERROR: ' + e.message);
});
</script>
</body></html>"""


# ── API: Status ───────────────────────────────────────────


@app.get("/api/status")
async def status():
    return {
        "status": "online",
        "provider": PROVIDER,
        "model": ACTIVE_MODEL,
        "tools": len(registry.tools),
        "uptime": time.time(),
        "framework": "fastapi",
        "streaming": "websocket+sse",
    }


@app.get("/api/me")
async def me(_auth=Depends(verify_auth)):
    return {"authenticated": True, "session": "web:default"}


@app.get("/api/traces")
async def traces(limit: int = 50, _auth=Depends(verify_auth)):
    """List recent run_ids with a one-line summary for browsing."""
    from ..core.tracing import tracer
    from ..memory import memory_store

    if not tracer._store:
        tracer.set_store(memory_store)

    limit = max(1, min(limit, 200))
    return {"traces": tracer.list_runs(limit)}


@app.get("/api/trace/{run_id}")
async def trace(run_id: str, _auth=Depends(verify_auth)):
    """Return the full nested span tree for a run_id."""
    from ..core.tracing import tracer
    from ..memory import memory_store

    if not tracer._store:
        tracer.set_store(memory_store)

    tree = tracer.get_run_tree(run_id)
    if tree is None:
        raise HTTPException(status_code=404, detail=f"No trace found for run_id: {run_id}")
    return tree


# ── API: Chat (SSE streaming) ────────────────────────────


@app.post("/api/chat")
async def chat(request: ChatRequest, _auth=Depends(verify_auth)):
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="No message provided")

    session_id = request.session_id
    tab_id = request.tab_id
    queue = asyncio.Queue()
    loop = asyncio.get_event_loop()

    def stream_event(event, payload):
        try:
            flat = {"type": event}
            flat.update(payload)
            loop.call_soon_threadsafe(queue.put_nowait, flat)
        except Exception:
            pass

    async def event_generator():

        # Check if session is busy — queue the message
        if session_manager.is_busy(session_id):
            pos = session_manager.queue_message(session_id, message)
            if pos < 0:
                yield 'data: {"type": "error", "text": "Queue full — try again shortly."}\n\n'
            else:
                yield f'data: {{"type": "busy", "text": "Queued (position {pos}). Processing after current task."}}\n\n'
            yield 'data: {"event": "done"}\n\n'
            return

        def run_agent():
            try:
                response = session_manager.process(session_id, message, emit=stream_event)
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "response", "text": response})
            except NallyError as e:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "text": e.to_llm_format()})
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "text": str(e)})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        # Clear any prior abort flag for this session
        from ..core.abort import clear_abort

        clear_abort(session_id)

        # Broadcast user message immediately to other tabs
        broadcast_manager.broadcast("user_message", {"text": message, "tab_id": tab_id})

        asyncio.ensure_future(loop.run_in_executor(None, run_agent))

        while True:
            # Check for abort
            if check_abort(session_id):
                from ..core.abort import clear_abort

                clear_abort(session_id)
                yield 'data: {"type": "error", "text": "Operation aborted by user."}\n\n'
                yield 'data: {"event": "done"}\n\n'
                return
            item = await queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item)}\n\n"

            # Broadcast specific events to other tabs
            evt_type = item.get("type", "")
            if evt_type == "thought":
                broadcast_manager.broadcast("thinking", {"text": item.get("text", ""), "tab_id": tab_id})
            elif evt_type == "response":
                broadcast_manager.broadcast("assistant_message", {"text": item.get("text", ""), "tab_id": tab_id})

        yield 'data: {"event": "done"}\n\n'

    response = StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )
    return response


# ── API: Persistent SSE (multi-tab sync) ──────────────────


@app.get("/api/events")
async def sse_events(request: Request):
    """Persistent SSE connection for real-time multi-tab sync.
    Uses query param auth since EventSource doesn't support headers."""
    # Auth via query param (EventSource can't set headers)
    token = request.query_params.get("token", "")
    if not NALLY_ACCESS_TOKEN or not hmac.compare_digest(token, NALLY_ACCESS_TOKEN):
        raise HTTPException(status_code=401, detail="Unauthorized")

    cid, queue = broadcast_manager.subscribe()
    broadcast_manager._loop = asyncio.get_event_loop()

    async def event_stream():
        try:
            # Send initial snapshot
            yield "event: connected\ndata: {}\n\n"
            while True:
                payload = await queue.get()
                yield payload
        except asyncio.CancelledError:
            pass
        finally:
            broadcast_manager.unsubscribe(cid)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


# ── API: History ──────────────────────────────────────────


@app.get("/api/history")
async def history(_auth=Depends(verify_auth)):
    messages = [
        {"role": msg.get("role", "unknown"), "content": msg.get("content", "")}
        for msg in session_manager.get_history("web:default")
    ]
    return {"messages": [m for m in messages if m.get("role") not in ("system", "tool")]}


# ── API: Clear ────────────────────────────────────────────


@app.post("/api/clear")
async def clear(_auth=Depends(verify_auth)):
    agent = session_manager.get("web:default")
    agent.clear_history()
    broadcast_manager.broadcast("history_cleared", {})
    return {"status": "cleared"}


# ── API: Approval ─────────────────────────────────────────


@app.post("/api/approve")
async def approval_response(request: ApprovalRequest, _auth=Depends(verify_auth)):
    from nally.agent.graph import resolve_approval

    # resolve_approval does blocking SQLite I/O — keep it off the event loop.
    await asyncio.to_thread(resolve_approval, request.tool_call_id, request.approved)
    broadcast_manager.broadcast(
        "approval_resolved", {"tool_call_id": request.tool_call_id, "approved": request.approved}
    )
    return {"ok": True}


# ── API: Telegram (bot runs as a separate process) ────────
# The bot polls Telegram in its own process and forwards messages/approvals
# here over HTTP. The agent + approval gate live in THIS process, so resolving
# an approval here unblocks the gate that is waiting in this process.


@app.post("/api/telegram/message")
async def tg_message(request: Request):
    data = await request.json()
    from ..agent.sessions import session_manager
    from ..telegram.bot import _make_emit_standalone

    emit = _make_emit_standalone(data["chat_id"])
    response = await asyncio.to_thread(
        session_manager.process, data["session_id"], data["text"], emit=emit
    )
    return {"response": response}


@app.post("/api/telegram/approve")
async def tg_approve(request: Request):
    data = await request.json()
    from ..agent.graph import resolve_approval

    # resolve_approval does blocking SQLite I/O — keep it off the event loop.
    resolved = await asyncio.to_thread(resolve_approval, data["tc_id"], data["approved"])
    return {"resolved": resolved}


# ── API: Abort ────────────────────────────────────────────


def check_abort(session_id: str = "web:default") -> bool:
    from ..core.abort import check_abort as _check

    return _check(session_id)


@app.post("/api/abort")
async def abort_session(session_id: str = "web:default", _auth=Depends(verify_auth)):
    from ..core.abort import set_abort

    set_abort(session_id)
    return {"status": "aborted"}


@app.post("/api/abort/clear")
async def abort_clear(session_id: str = "web:default", _auth=Depends(verify_auth)):
    from ..core.abort import clear_abort

    clear_abort(session_id)
    return {"status": "cleared"}


# ── API: Permissions ──────────────────────────────────────


@app.get("/api/permissions")
async def get_permissions(_auth=Depends(verify_auth)):
    from nally.tools.permissions import get_config

    return {"permissions": get_config()}


@app.get("/api/skills")
async def get_skills(_auth=Depends(verify_auth)):
    """List available skills with their descriptions and allowed tools."""
    from nally.skills.registry import skill_registry

    if not skill_registry._loaded:
        skill_registry.load()
    skills = []
    for name in sorted(skill_registry.names):
        skill = skill_registry.get(name)
        if skill:
            skills.append(
                {
                    "name": name,
                    "description": skill.description,
                    "allowed_tools": skill.allowed_tools,
                    "warnings": skill.warnings,
                }
            )
    return {"skills": skills, "count": len(skills)}


# ── API: MCP Services ────────────────────────────────────


@app.get("/api/mcp/services")
async def mcp_services(_auth=Depends(verify_auth)):
    """List available MCP services and their connection status."""
    import os

    from nally.config import MCP_SERVERS
    from nally.mcp.oauth import get_existing_tokens

    db = str(DATA_DIR / "nally.db")
    services = []
    for server in MCP_SERVERS:
        name = server["name"]
        auth_mode = server.get("auth_mode", "")
        transport = server["transport"]

        if transport == "stdio" and auth_mode == "api_key":
            # Stdio services with env var token — check if env var is set
            env_key = server.get("env_key", "")
            token_set = bool(os.getenv(env_key, ""))
            services.append(
                {
                    "name": name,
                    "transport": transport,
                    "auth_mode": auth_mode,
                    "description": server.get("description", ""),
                    "connected": token_set,
                }
            )
        else:
            token = await get_existing_tokens(name, db)
            services.append(
                {
                    "name": name,
                    "transport": transport,
                    "auth_mode": auth_mode,
                    "description": server.get("description", ""),
                    "connected": token is not None,
                }
            )
    return {"services": services}


@app.post("/api/mcp/connect/{service}")
async def mcp_connect(service: str, _auth=Depends(verify_auth)):
    """Initiate connection for an MCP service.

    OAuth services: returns auth_url for browser redirect.
    API key services: returns status.
    """
    from nally.config import DATA_DIR, MCP_SERVERS
    from nally.mcp.oauth import get_existing_tokens

    server_cfg = next((s for s in MCP_SERVERS if s["name"] == service), None)
    if server_cfg is None:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service}")

    db = str(DATA_DIR / "nally.db")
    auth_mode = server_cfg.get("auth_mode", "")

    # Check if already connected
    existing = await get_existing_tokens(service, db)
    if existing:
        broadcast_manager.broadcast("mcp_status", {"service": service, "connected": True})
        return {"status": "connected", "service": service}

    if auth_mode == "oauth":
        # Start OAuth flow — return auth_url for browser redirect
        if service == "notion":
            from nally.mcp.oauth import start_notion_oauth

            try:
                auth_url = await start_notion_oauth(db)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            return {"status": "auth_required", "auth_url": auth_url, "service": service}
        elif service in ("gmail", "gdrive", "gcalendar"):
            from nally.mcp.oauth import start_google_oauth

            try:
                auth_url = await start_google_oauth(service, db)
                return {"status": "auth_required", "auth_url": auth_url, "service": service}
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
        elif service == "higgsfield":
            from nally.mcp.oauth import start_higgsfield_oauth

            try:
                auth_url = await start_higgsfield_oauth(db)
            except ValueError as e:
                raise HTTPException(status_code=400, detail=str(e))
            return {"status": "auth_required", "auth_url": auth_url, "service": service}
        else:
            raise HTTPException(status_code=400, detail=f"OAuth not configured for {service}")

    return {"status": "disconnected", "service": service}


class TokenSubmit(BaseModel):
    token: str


@app.post("/api/mcp/token/{service}")
async def mcp_submit_token(service: str, body: TokenSubmit, _auth=Depends(verify_auth)):
    """Submit a PAT/API token for an HTTP MCP service, or bot token for stdio."""
    from mcp.shared.auth import OAuthToken

    from nally.config import DATA_DIR, MCP_SERVERS
    from nally.mcp.oauth import SQLiteTokenStorage

    server_cfg = next((s for s in MCP_SERVERS if s["name"] == service), None)
    if server_cfg is None:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service}")

    db = str(DATA_DIR / "nally.db")
    transport = server_cfg.get("transport", "http")

    if transport == "stdio":
        # Stdio service (e.g. Telegram) — store token in env and connect
        env_key = server_cfg.get("env_key", "")
        if env_key:
            import os

            os.environ[env_key] = body.token
        from nally.mcp.client import connect_stdio_with_token

        try:
            count = connect_stdio_with_token(server_cfg)
        except Exception:
            count = 0
        broadcast_manager.broadcast("mcp_status", {"service": service, "connected": True})
        return {"status": "connected", "service": service, "tools": count}

    # HTTP service — store as OAuthToken
    storage = SQLiteTokenStorage(db, service)
    token = OAuthToken(access_token=body.token, token_type="bearer")
    await storage.set_tokens(token)

    from nally.mcp.client import connect_http_server

    try:
        count = await connect_http_server(server_cfg)
    except Exception:
        count = 0

    broadcast_manager.broadcast("mcp_status", {"service": service, "connected": True})
    return {"status": "connected", "service": service, "tools": count}


# ── API: OAuth Callbacks ──────────────────────────────────

REDIRECT_HTML = """<!DOCTYPE html>
<html><head><title>Authorized</title>
<style>body{background:#0a0a0a;color:#3ECFB8;font-family:monospace;display:flex;align-items:center;justify-content:center;height:100vh;margin:0;}
.msg{text-align:center;}.check{font-size:48px;margin-bottom:16px;}</style>
</head><body>
<div class="msg"><div class="check">✓</div><div>SERVICE authorized successfully</div>
<div style="color:#666;font-size:12px;margin-top:8px;">Redirecting...</div></div>
<script>setTimeout(function(){window.location='/?oauth=success&service=SERVICE';},800);</script>
</body></html>"""


@app.get("/api/oauth/notion/callback")
async def notion_oauth_callback(code: str = "", state: str = "", error: str = ""):
    """Notion OAuth callback — exchanges code for tokens."""
    if error:
        return JSONResponse(status_code=400, content={"error": error})
    if not code:
        return JSONResponse(status_code=400, content={"error": "missing_code"})

    from nally.config import DATA_DIR, MCP_SERVERS
    from nally.mcp.client import connect_http_server
    from nally.mcp.oauth import exchange_notion_code

    db = str(DATA_DIR / "nally.db")
    success = await exchange_notion_code(code, db)
    if not success:
        return JSONResponse(status_code=400, content={"error": "token_exchange_failed"})

    # Connect and fetch tools
    server_cfg = next((s for s in MCP_SERVERS if s["name"] == "notion"), None)
    if server_cfg:
        try:
            await connect_http_server(server_cfg)
        except Exception:
            pass

    html = REDIRECT_HTML.replace("SERVICE", "notion")
    return HTMLResponse(content=html)


@app.get("/api/oauth/google/callback")
async def google_oauth_callback(code: str = "", state: str = "", error: str = ""):
    """Google OAuth callback — exchanges code for tokens (shared by Gmail/Drive/Calendar)."""
    if error:
        return JSONResponse(status_code=400, content={"error": error})
    if not code:
        return JSONResponse(status_code=400, content={"error": "missing_code"})

    from nally.config import DATA_DIR, MCP_SERVERS
    from nally.mcp.client import connect_http_server
    from nally.mcp.oauth import GOOGLE_SERVICES, exchange_google_code

    db = str(DATA_DIR / "nally.db")
    success = await exchange_google_code(code, db)
    if not success:
        return JSONResponse(status_code=400, content={"error": "token_exchange_failed"})

    # Connect and fetch tools for all Google services
    for svc_name in GOOGLE_SERVICES:
        server_cfg = next((s for s in MCP_SERVERS if s["name"] == svc_name), None)
        if server_cfg:
            try:
                await connect_http_server(server_cfg)
            except Exception:
                pass

    html = REDIRECT_HTML.replace("SERVICE", "gmail")
    return HTMLResponse(content=html)


@app.get("/api/oauth/higgsfield/callback")
async def higgsfield_oauth_callback(code: str = "", state: str = "", error: str = ""):
    """Higgsfield OAuth callback — exchanges code for tokens."""
    if error:
        return JSONResponse(status_code=400, content={"error": error})
    if not code:
        return JSONResponse(status_code=400, content={"error": "missing_code"})

    from nally.config import DATA_DIR, MCP_SERVERS
    from nally.mcp.client import connect_http_server
    from nally.mcp.oauth import exchange_higgsfield_code

    db = str(DATA_DIR / "nally.db")
    success = await exchange_higgsfield_code(code, db)
    if not success:
        return JSONResponse(status_code=400, content={"error": "token_exchange_failed"})

    # Connect and fetch tools
    server_cfg = next((s for s in MCP_SERVERS if s["name"] == "higgsfield"), None)
    if server_cfg:
        try:
            await connect_http_server(server_cfg)
        except Exception:
            pass

    html = REDIRECT_HTML.replace("SERVICE", "higgsfield")
    return HTMLResponse(content=html)


@app.post("/api/mcp/disconnect/{service}")
async def mcp_disconnect(service: str, _auth=Depends(verify_auth)):
    """Disconnect an MCP service by removing stored tokens."""
    from nally.config import DATA_DIR
    from nally.mcp.oauth import GOOGLE_SERVICES, revoke_service

    db = str(DATA_DIR / "nally.db")

    # Google services share one token — disconnect all
    if service in GOOGLE_SERVICES:
        for svc in GOOGLE_SERVICES:
            revoke_service(svc, db)
        return {"status": "disconnected"}

    removed = revoke_service(service, db)
    if removed:
        broadcast_manager.broadcast("mcp_status", {"service": service, "connected": False})
    return {"status": "disconnected" if removed else "not_connected"}


@app.post("/api/env/{key}")
async def set_env_var(key: str, body: TokenSubmit, _auth=Depends(verify_auth)):
    """Set an environment variable at runtime and persist to .env file."""

    os.environ[key] = body.token

    # Persist to .env file
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"
    lines = []
    found = False
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith(f"{key}="):
                lines.append(f"{key}={body.token}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{key}={body.token}")
    env_path.write_text("\n".join(lines) + "\n")

    return {"ok": True, "key": key}


# ── WebSocket: Real-time chat ──────────────────────────────


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocket endpoint for real-time bidirectional chat.

    Connect with: ws://localhost:5000/ws/web:default?token=<access_token>
    """
    from .ws_handler import websocket_chat

    await websocket_chat(websocket, session_id)


# ── Telegram Webhook ──────────────────────────────────────

@app.post("/telegram/webhook/{token}")
async def telegram_webhook(token: str, request: Request):
    """Receive Telegram updates via webhook (no polling needed)."""
    from ..config import TELEGRAM_BOT_TOKEN

    # Verify token matches
    if token != TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")

    # Get the Telegram bot app
    tg_app = app.state.telegram_app
    if not tg_app:
        raise HTTPException(status_code=503, detail="Telegram bot not ready")

    # Process the update
    from telegram import Update

    data = await request.json()
    update = Update.de_json(data, tg_app.bot)
    await tg_app.process_update(update)

    return {"status": "ok"}


# ── Run server ────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 5000))
    print(f"\n  Nally Jarvis starting on http://localhost:{port}")
    print("  Press Ctrl+C to stop\n")

    def _open_browser():
        time.sleep(1.5)
        webbrowser.open(f"http://localhost:{port}")

    import threading

    threading.Thread(target=_open_browser, daemon=True).start()

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
