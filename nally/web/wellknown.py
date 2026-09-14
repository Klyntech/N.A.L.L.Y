"""Well-Known endpoints — receipts pubkey + agent card + NLWeb.

- /.well-known/nally-receipt-pubkey  Ed25519 JWK for receipt verification (lesson 18)
- /.well-known/agent.json             A2A agent card (lesson 11)
- /llms.txt                           NLWeb natural-language affordances
- POST /a2a/rpc                        Minimal A2A JSON-RPC (sendTask)
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, PlainTextResponse

router = APIRouter()


@router.get("/.well-known/nally-receipt-pubkey")
async def receipt_pubkey():
    """Ed25519 public key for verifying tool receipts (JWK). No auth."""
    try:
        from ..tools.receipts import receipt_store

        b64 = receipt_store.get_public_key()
        if not b64:
            return JSONResponse({"error": "no key configured"}, status_code=404)
        # JWK OKP Ed25519 per RFC 8037
        return JSONResponse(
            {
                "kty": "OKP",
                "crv": "Ed25519",
                "x": b64,
                "alg": "EdDSA",
                "use": "sig",
                "kid": b64[:16],
            }
        )
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@router.get("/.well-known/agent.json")
@router.get("/.well-known/agent-card.json")
async def agent_card(request: Request):
    """A2A agent card — discovery for peer agents (lesson 11). No auth."""
    try:
        from ..config import NALLY_BASE_URL

        base = NALLY_BASE_URL or str(request.base_url).rstrip("/")
        version = "1.0.0"
        try:
            import tomllib
            from pathlib import Path

            p = Path(__file__).parent.parent.parent / "pyproject.toml"
            if p.exists():
                with open(p, "rb") as f:
                    version = tomllib.load(f).get("project", {}).get("version", version)
        except Exception:
            pass

        card = {
            "name": "NALLY",
            "description": "NALLY — autonomous reasoning system, not a chatbot. Understand, act through tools, verify against evidence.",
            "version": version,
            "provider": "nally",
            "url": base,
            "capabilities": {
                "mcp": True,
                "a2a": True,
                "streaming": True,
                "receipts": "ed25519+jcs",
                "tools": "openai-compatible",
            },
            "endpoints": {
                "chat": f"{base}/api/chat",
                "health": f"{base}/health",
                "receipt_pubkey": f"{base}/.well-known/nally-receipt-pubkey",
                "a2a_rpc": f"{base}/a2a/rpc",
            },
            "a2a": {
                "protocol": "json-rpc-2.0",
                "methods": ["agent.getCard", "task.send", "task.get"],
            },
        }
        return JSONResponse(card)
    except Exception as e:
        return JSONResponse({"error": str(e)[:200]}, status_code=500)


@router.get("/llms.txt")
async def llms_txt():
    """NLWeb affordance — natural-language endpoint descriptions for crawlers/agents."""
    txt = """# NALLY — llms.txt (NLWeb)

User-Agent: *
Allow: /api/chat
Allow: /.well-known/agent.json
Allow: /.well-known/nally-receipt-pubkey
Allow: /health
Allow: /a2a/rpc
Allow: /docs

# Agent
NALLY is an autonomous reasoning system that gets things done: understand the request, act through tools, verify against evidence, answer truthfully.
- Chat: POST /api/chat {message, session_id} → SSE {event: stream_chunk|tool_call|response}
- Health: GET /health → {status, version, provider, model}
- Receipts: GET /.well-known/nally-receipt-pubkey → JWK Ed25519 (verify tool receipts, JCS)
- A2A: POST /a2a/rpc JSON-RPC {jsonrpc:"2.0", method:"task.send", params:{input, session_id}, id:1}
- Docs: GET /docs (OpenAPI)

# Tools
Tool schemas are OpenAI-compatible via POST /api/chat tool filtering (CapabilityRouter + permission gate).
See /.well-known/agent.json for card and /api/chat for live capabilities.
"""
    return PlainTextResponse(txt, media_type="text/plain")


# ── Minimal A2A JSON-RPC ───────────────────────────────────────────────

@router.post("/a2a/rpc")
async def a2a_rpc(request: Request):
    """Minimal A2A JSON-RPC — task.send forwards to session_manager (lesson 11).

    Body: {jsonrpc:"2.0", id:1, method:"task.send"|"agent.getCard"|"task.get", params:{input, session_id}}
    No auth for getCard; task.send requires Bearer NALLY_ACCESS_TOKEN if configured.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}, "id": None}, status_code=400)

    jid = body.get("id")
    method = body.get("method", "")
    params = body.get("params", {}) or {}

    if method == "agent.getCard":
        card = await agent_card(request)
        # agent_card returns JSONResponse — unwrap
        import json

        try:
            # card is JSONResponse, get body
            data = json.loads(card.body.decode())
        except Exception:
            data = {}
        return JSONResponse({"jsonrpc": "2.0", "result": data, "id": jid})

    if method in ("task.send", "task.create"):
        # Auth check when NALLY_ACCESS_TOKEN set
        try:
            import os

            expected = os.getenv("NALLY_ACCESS_TOKEN", "").strip()
            if expected:
                auth = request.headers.get("authorization", "")
                token = auth.removeprefix("Bearer ").strip() if auth.lower().startswith("bearer ") else ""
                if token != expected:
                    return JSONResponse(
                        {"jsonrpc": "2.0", "error": {"code": -32001, "message": "Unauthorized"}, "id": jid},
                        status_code=401,
                    )
        except Exception:
            pass

        inp = params.get("input") or params.get("message") or ""
        sess = params.get("session_id") or params.get("sessionId") or "a2a:default"
        if not inp:
            return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32602, "message": "Missing params.input"}, "id": jid}, status_code=400)

        try:
            from ..agent.sessions import session_manager

            # Run via session_manager (same brain as web:default, isolated route_key)
            result = await _run_a2a_task(inp, sess)
            return JSONResponse({"jsonrpc": "2.0", "result": {"output": result, "session_id": sess}, "id": jid})
        except Exception as e:
            return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32000, "message": str(e)[:300]}, "id": jid}, status_code=500)

    if method == "task.get":
        return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Method not found: {method}"}, "id": jid}, status_code=404)

    return JSONResponse({"jsonrpc": "2.0", "error": {"code": -32601, "message": f"Method not found: {method}"}, "id": jid}, status_code=404)


async def _run_a2a_task(inp: str, session_id: str) -> str:
    """Run a task via NallyAgent in threadpool (non-blocking)."""
    import asyncio

    loop = asyncio.get_event_loop()
    from ..agent.sessions import session_manager

    # Use session_manager.process which handles queue + brain routing
    def _sync():
        # session_manager.process is sync (wraps agent.process)
        return session_manager.process(session_id, inp)

    return await loop.run_in_executor(None, _sync)
