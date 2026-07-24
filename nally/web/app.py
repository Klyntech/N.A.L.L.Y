"""Nally Web Server - FastAPI backend with SSE streaming"""
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
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from nally.tools import load_all_tools
from nally.tools.registry import registry
from nally.agent import get_agent
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
    if credentials and credentials.credentials == NALLY_ACCESS_TOKEN:
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

@app.get("/")
async def index():
    return FileResponse(str(_base / "web" / "index.html"))


@app.get("/vendor/{filename:path}")
async def vendor_static(filename: str):
    resp = FileResponse(str(_base / "web" / "vendor" / filename), media_type="application/javascript")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.get("/js/{filename:path}")
async def js_static(filename: str):
    resp = FileResponse(str(_base / "web" / "js" / filename), media_type="application/javascript")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


@app.get("/css/{filename:path}")
async def css_static(filename: str):
    resp = FileResponse(str(_base / "web" / "css" / filename), media_type="text/css")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    return resp


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

    queue = asyncio.Queue()

    def stream_event(event, payload):
        try:
            flat = {"type": event}
            flat.update(payload)
            loop.call_soon_threadsafe(queue.put_nowait, flat)
        except Exception:
            pass

    async def event_generator():
        loop = asyncio.get_event_loop()

        def run_agent():
            try:
                agent = get_agent()
                response = agent.process(message, emit=stream_event)
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

        asyncio.ensure_future(loop.run_in_executor(None, run_agent))

        while True:
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


# ── API: Chat (non-streaming) ────────────────────────────

@app.post("/api/jarvis")
async def jarvis_chat(request: ChatRequest, _auth=Depends(verify_auth)):
    prompt = request.message.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="No prompt provided")
    try:
        response = get_agent().process(prompt)
        return {"text": response, "status": "ok"}
    except NallyError as e:
        return {"text": e.to_llm_format(), "status": "error", "fallback": True}
    except Exception as e:
        return {"text": f"System error: {str(e)}", "status": "error", "fallback": True}


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

@app.post("/api/approval")
async def approval_response(request: ApprovalRequest, _auth=Depends(verify_auth)):
    from nally.agent.graph import resolve_approval
    resolve_approval(request.tool_call_id, request.approved)
    return {"ok": True}


# ── API: Permissions ──────────────────────────────────────

@app.get("/api/permissions")
async def get_permissions(_auth=Depends(verify_auth)):
    from nally.tools.permissions import get_config
    return {"permissions": get_config()}


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
