"""Nally Web Server - FastAPI backend with SSE streaming"""
import hmac
import json
import time
import os
import sys
import asyncio
import uuid
import webbrowser
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse, RedirectResponse, HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from nally.tools import load_all_tools
from nally.tools.registry import registry
from nally.agent import get_agent
from nally.agent.sessions import session_manager
from nally.config import (
    PROVIDER, ACTIVE_MODEL, ALLOWED_ORIGINS,
    RATE_LIMIT_ENABLED, RATE_LIMIT_RPM, RATE_LIMIT_BURST,
    ensure_data_dir, DATA_DIR,
)
from nally.core.errors import NallyError
from nally.utils.logger import logger


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


class ApprovalRequest(BaseModel):
    tool_call_id: str
    approved: bool


# ── Lifespan ──────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_data_dir()
    load_all_tools()
    logger.info("Tools loaded.")

    def _prewarm():
        try:
            logger.info("Pre-warming agent in background...")
            get_agent()
            logger.info("Agent ready.")
        except Exception as e:
            logger.warning(f"Agent pre-warm failed: {e}")

    import threading
    threading.Thread(target=_prewarm, daemon=True).start()

    if not NALLY_ACCESS_TOKEN:
        logger.error("NALLY_ACCESS_TOKEN not set — refusing to start without auth")
        raise RuntimeError("NALLY_ACCESS_TOKEN not set")

    logger.info("Lifespan startup complete.")
    yield
    logger.info("Lifespan shutdown.")


# ── App ───────────────────────────────────────────────────

app = FastAPI(title="Nally", lifespan=lifespan)

# CORS from config
_origins = ALLOWED_ORIGINS if isinstance(ALLOWED_ORIGINS, list) else [o.strip() for o in ALLOWED_ORIGINS.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Middleware: rate limit + request ID ───────────────────

@app.middleware("http")
async def _middleware(request: Request, call_next):
    # Rate limit
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

@app.get("/")
async def index():
    return FileResponse(str(_web_dir / "index.html"))

# Serve JS/CSS assets from web/ directory
app.mount("/static", StaticFiles(directory=str(_web_dir)), name="static")


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
        "streaming": "sse",
    }


# ── API: Chat (SSE streaming) ────────────────────────────

@app.post("/api/chat")
async def chat(request: ChatRequest, _auth=Depends(verify_auth)):
    message = request.message.strip()
    if not message:
        raise HTTPException(status_code=400, detail="No message provided")

    session_id = request.session_id
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

        def run_agent():
            try:
                response = session_manager.process(session_id, message, emit=stream_event)
                loop.call_soon_threadsafe(
                    queue.put_nowait, {"type": "response", "text": response}
                )
            except NallyError as e:
                loop.call_soon_threadsafe(
                    queue.put_nowait, {"type": "error", "text": e.to_llm_format()}
                )
            except Exception as e:
                loop.call_soon_threadsafe(
                    queue.put_nowait, {"type": "error", "text": str(e)}
                )
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        # Clear any prior abort flag for this session
        _abort_flags.pop(session_id, None)

        asyncio.ensure_future(loop.run_in_executor(None, run_agent))

        while True:
            # Check for abort
            if _abort_flags.get(session_id):
                _abort_flags.pop(session_id, None)
                yield 'data: {"type": "error", "text": "Operation aborted by user."}\n\n'
                yield 'data: {"event": "done"}\n\n'
                return
            item = await queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item)}\n\n"
        yield 'data: {"event": "done"}\n\n'

    return StreamingResponse(
        event_generator(),
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
        for msg in get_agent().get_history()
    ]
    return {"messages": messages}


# ── API: Clear ────────────────────────────────────────────

@app.post("/api/clear")
async def clear(_auth=Depends(verify_auth)):
    get_agent().clear_history()
    return {"status": "cleared"}


# ── API: Approval ─────────────────────────────────────────

@app.post("/api/approve")
async def approval_response(request: ApprovalRequest, _auth=Depends(verify_auth)):
    from nally.agent.graph import resolve_approval
    resolve_approval(request.tool_call_id, request.approved)
    return {"ok": True}


# ── API: Abort ────────────────────────────────────────────

_abort_flags: dict[str, bool] = {}

def check_abort(session_id: str = "web:default") -> bool:
    return _abort_flags.get(session_id, False)

@app.post("/api/abort")
async def abort_session(session_id: str = "web:default", _auth=Depends(verify_auth)):
    _abort_flags[session_id] = True
    return {"status": "aborted"}

@app.post("/api/abort/clear")
async def abort_clear(session_id: str = "web:default", _auth=Depends(verify_auth)):
    _abort_flags.pop(session_id, None)
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
            skills.append({
                "name": name,
                "description": skill.description,
                "allowed_tools": skill.allowed_tools,
                "warnings": skill.warnings,
            })
    return {"skills": skills, "count": len(skills)}


# ── API: MCP Services ────────────────────────────────────

@app.get("/api/mcp/services")
async def mcp_services(_auth=Depends(verify_auth)):
    """List available MCP services and their connection status."""
    from nally.config import MCP_SERVERS
    from nally.mcp.oauth import get_existing_tokens
    import os

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
            services.append({
                "name": name,
                "transport": transport,
                "auth_mode": auth_mode,
                "description": server.get("description", ""),
                "connected": token_set,
            })
        else:
            token = await get_existing_tokens(name, db)
            services.append({
                "name": name,
                "transport": transport,
                "auth_mode": auth_mode,
                "description": server.get("description", ""),
                "connected": token is not None,
            })
    return {"services": services}


@app.post("/api/mcp/connect/{service}")
async def mcp_connect(service: str, _auth=Depends(verify_auth)):
    """Initiate connection for an MCP service.

    OAuth services: returns auth_url for browser redirect.
    API key services: returns status.
    """
    from nally.config import MCP_SERVERS, DATA_DIR
    from nally.mcp.oauth import SQLiteTokenStorage, get_existing_tokens

    server_cfg = next((s for s in MCP_SERVERS if s["name"] == service), None)
    if server_cfg is None:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service}")

    db = str(DATA_DIR / "nally.db")
    auth_mode = server_cfg.get("auth_mode", "")

    # Check if already connected
    existing = await get_existing_tokens(service, db)
    if existing:
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
        else:
            raise HTTPException(status_code=400, detail=f"OAuth not configured for {service}")

    return {"status": "disconnected", "service": service}


class TokenSubmit(BaseModel):
    token: str

@app.post("/api/mcp/token/{service}")
async def mcp_submit_token(service: str, body: TokenSubmit, _auth=Depends(verify_auth)):
    """Submit a PAT/API token for an HTTP MCP service, or bot token for stdio."""
    from nally.config import MCP_SERVERS, DATA_DIR
    from nally.mcp.oauth import SQLiteTokenStorage
    from mcp.shared.auth import OAuthToken

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

    from nally.config import DATA_DIR
    from nally.mcp.oauth import exchange_notion_code
    from nally.mcp.client import connect_http_server
    from nally.config import MCP_SERVERS

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
    from nally.mcp.oauth import exchange_google_code, GOOGLE_SERVICES
    from nally.mcp.client import connect_http_server

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


@app.post("/api/mcp/disconnect/{service}")
async def mcp_disconnect(service: str, _auth=Depends(verify_auth)):
    """Disconnect an MCP service by removing stored tokens."""
    from nally.config import DATA_DIR
    from nally.mcp.oauth import revoke_service, GOOGLE_SERVICES

    db = str(DATA_DIR / "nally.db")

    # Google services share one token — disconnect all
    if service in GOOGLE_SERVICES:
        for svc in GOOGLE_SERVICES:
            revoke_service(svc, db)
        return {"status": "disconnected"}

    removed = revoke_service(service, db)
    return {"status": "disconnected" if removed else "not_connected"}


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
