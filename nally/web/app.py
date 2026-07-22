"""Nally Web Server - FastAPI backend with SSE streaming"""
import json
import time
import os
import sys
import asyncio
import webbrowser
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.responses import StreamingResponse, JSONResponse, FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Import Nally agent
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from nally.tools import load_all_tools
from nally.tools.registry import registry
from nally.agent import get_agent
from nally.config import SYSTEM_PROMPT, PROVIDER, ACTIVE_MODEL

# Handle PyInstaller frozen paths
if getattr(sys, 'frozen', False):
    _base = Path(sys.executable).parent
    _mei = Path(sys._MEIPASS)
else:
    _base = Path(__file__).parent.parent.parent

# Auth config
NALLY_ACCESS_TOKEN = os.environ.get("NALLY_ACCESS_TOKEN", "")
security = HTTPBearer(auto_error=False)

# Track streaming events for diagnostic logs
streaming_logs = []
js_errors = []


# --- Auth dependency ---

async def verify_auth(credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)):
    if credentials and credentials.credentials == NALLY_ACCESS_TOKEN:
        return True
    raise HTTPException(status_code=401, detail="Unauthorized")


# --- Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_all_tools()
    print("[NALLY] Tools loaded.")

    def _prewarm():
        try:
            print("[NALLY] Pre-warming agent in background...")
            get_agent()
            print("[NALLY] Agent ready.")
        except Exception as e:
            print(f"[NALLY] Agent pre-warm failed: {e}")

    import threading
    threading.Thread(target=_prewarm, daemon=True).start()

    # Auto-seed user profile
    _profile_path = _base / "data" / "user_profile.json"
    if not _profile_path.exists():
        _profile_path.parent.mkdir(parents=True, exist_ok=True)
        _default_profile = {
            "name": "Clinton Onyedikachi Chukwuma",
            "preferred_name": "Clinton",
            "aliases": ["Klyntech", "Klynvybz", "Klyntyn"],
            "age": 17,
            "location": "Lagos, Nigeria",
            "occupation": "Coding Student & AI Developer",
            "education": "Processing admission to ABSU (Abia State University) - Law",
            "communication_style": "concise",
            "timezone": "Africa/Lagos",
            "languages_spoken": ["English", "Igbo"],
            "languages_to_learn": ["Russian", "Spanish", "French"],
            "coding_level": "Beginner",
            "coding_languages": ["Python", "JavaScript", "TypeScript", "C", "C++"],
            "projects": ["Nally (AI agent)", "Tradeknox (trading bot)"],
            "goals": ["Build a company that handles big money", "Be powerful", "Be global", "Learn Russian, Spanish, French"],
            "interests": ["coding", "AI", "building software", "trading"],
            "favorite_apps": [],
            "work_hours": "",
            "notes": "Clinton is building something massive. He's 17, studying law while coding. He wants to be global and powerful. Never mention ADHD or medical conditions.",
            "created": "2026-07-11T10:00:00",
            "updated": "2026-07-11T10:00:00"
        }
        _profile_path.write_text(json.dumps(_default_profile, indent=2, default=str), encoding="utf-8")
        print(f"[NALLY] Seeded user profile at {_profile_path}")

    if not NALLY_ACCESS_TOKEN:
        print("[FATAL] NALLY_ACCESS_TOKEN not set — refusing to start without auth", file=sys.stderr)
        print("[FATAL] Set it: export NALLY_ACCESS_TOKEN='your-secret-here'", file=sys.stderr)
        raise RuntimeError("NALLY_ACCESS_TOKEN not set")

    print("[NALLY] Lifespan startup complete.")
    yield
    print("[NALLY] Lifespan shutdown.")


# --- App ---

app = FastAPI(title="Nally", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- Static files ---

@app.get("/")
async def index():
    return FileResponse(str(_base / "web2" / "index.html"))


@app.get("/vendor/{filename:path}")
async def vendor_static(filename: str):
    return FileResponse(str(_base / "web2" / "vendor" / filename))


@app.get("/js/{filename:path}")
async def js_static(filename: str):
    return FileResponse(str(_base / "web2" / "js" / filename))


@app.get("/web2/")
async def web2_root():
    return RedirectResponse(url="/", status_code=302)



# --- JS Error Log ---

class JsError(BaseModel):
    error: dict = {}
    time: float = 0.0


@app.post("/api/js-error")
async def js_error(request: Request):
    data = await request.json()
    js_errors.append({"error": data, "time": time.time()})
    if len(js_errors) > 50:
        js_errors.pop(0)
    return {"ok": True}


@app.get("/api/js-errors")
async def get_js_errors():
    return {"errors": js_errors[-20:]}


# --- Debug Page ---

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
L('info', 'Server: FastAPI + SSE (no Socket.IO needed)');
L('info', 'Testing SSE connection...');
fetch('/api/status').then(r => r.json()).then(data => {
  L('ok', 'STATUS: ' + JSON.stringify(data));
}).catch(e => {
  L('fail', 'ERROR: ' + e.message);
});
</script>
</body></html>"""


# --- Chat Request Model ---

class ChatRequest(BaseModel):
    message: str


# --- API Endpoints ---

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
                # If no streaming happened, send the final response
                loop.call_soon_threadsafe(queue.put_nowait, {"event": "response", "data": {"response": response, "status": "ok"}})
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, {"event": "error", "data": {"response": str(e), "status": "error"}})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        async def _run_agent():
            await loop.run_in_executor(None, run_agent)
        asyncio.ensure_future(_run_agent())

        while True:
            item = await queue.get()
            if item is None:
                break
            yield f"data: {json.dumps(item)}\n\n"
        yield "data: {\"event\": \"done\"}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "X-Accel-Buffering": "no",
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )


@app.post("/api/jarvis")
async def jarvis_chat(request: ChatRequest, _auth=Depends(verify_auth)):
    prompt = request.message.strip()
    if not prompt:
        raise HTTPException(status_code=400, detail="No prompt provided")
    try:
        response = get_agent().process(prompt)
        return {"text": response, "status": "ok"}
    except Exception as e:
        return {"text": f"System error: {str(e)}", "status": "error", "fallback": True}


@app.get("/api/history")
async def history(_auth=Depends(verify_auth)):
    messages = []
    for msg in get_agent().get_history():
        messages.append({
            "role": msg.get("role", "unknown"),
            "content": msg.get("content", ""),
        })
    return {"messages": messages}


@app.post("/api/clear")
async def clear(_auth=Depends(verify_auth)):
    get_agent().clear_history()
    return {"status": "cleared"}


@app.get("/api/ui-commands")
async def get_ui_commands(_auth=Depends(verify_auth)):
    # tools.ui module not copied during migration
    return {"commands": []}


@app.get("/api/logs")
async def get_logs(_auth=Depends(verify_auth)):
    return {"logs": streaming_logs[-50:]}


# --- Gmail API Endpoints (disabled — nally/integrations not copied) ---
# To re-enable, copy nally/integrations/google/ and add google-api-python-client to requirements


# --- Telegram API Endpoints (disabled — nally/integrations not copied) ---
# To re-enable, copy nally/integrations/telegram/ and add httpx to requirements


# --- Approval endpoint (replaces Socket.IO approval_response) ---

class ApprovalRequest(BaseModel):
    tool_call_id: str
    approved: bool


@app.post("/api/approval")
async def approval_response(request: ApprovalRequest, _auth=Depends(verify_auth)):
    from nally.agent.graph import resolve_approval
    resolve_approval(request.tool_call_id, request.approved)
    return {"ok": True}


# --- Run server ---

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
