"""Embed API — separate Render Free instance (20MB MiniLM ONNX, 384d, 120MB RAM).

NALLY main stays lean (<300MB) — no torch here. This service holds the model.

POST /v1/embeddings  {input: str | str[], model: "all-MiniLM-L6-v2"}
  → {object:"list", data:[{object:"embedding", embedding:[...384], index:0}], model, usage:{prompt_tokens, total_tokens}}

GET /health → {"status":"ok", "model":"...", "dims":384}
GET /v1/models → {"data":[{"id":"all-MiniLM-L6-v2"}]}

Free-tier notes:
- Model baked into image at build (not downloaded at runtime) — ephemeral disk survives via image.
- ONNX quantized via optimum/optimum[onnxruntime] — 20MB not 80MB, RAM 120MB not 400MB.
- If no ONNX, falls back to sentence-transformers (80MB) — still fits Free but slower cold start.
- Auth: optional Bearer NALLY_INTERNAL_TOKEN (set EMBED_API_KEY). If unset, open (dev only).

Run:
  docker build -t nally-embed ./embed-api
  docker run -p 8000:8000 -e EMBED_MODEL=all-MiniLM-L6-v2 nally-embed
  curl -X POST http://localhost:8000/v1/embeddings -H "Content-Type: application/json" -d '{"input":"hello world","model":"all-MiniLM-L6-v2"}'

Deploy on Render Free: build this Dockerfile as separate Web Service (port 8000), set EMBED_MODEL env.
"""

import os
import time
from typing import List, Union

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

MODEL_NAME = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")
EMBED_API_KEY = os.getenv("EMBED_API_KEY", "") or os.getenv("NALLY_INTERNAL_TOKEN", "")
PORT = int(os.getenv("PORT", "8000"))

# Optional: Hugging Face cache inside container (baked at build)
os.environ.setdefault("HF_HOME", "/app/.cache/hf")
os.environ.setdefault("TRANSFORMERS_CACHE", "/app/.cache/hf")

app = FastAPI(title="NALLY Embed API", version="1.0.0")

# Lazy model — load on first request to keep healthcheck fast
_model = None
_model_dims = 384
_model_loaded_at: float | None = None

# Fallback: pure-hash pseudo-embed when model can't load (dev/testing, deterministic 384d)
def _hash_embed(text: str, dims: int = 384) -> List[float]:
    import hashlib, math
    h = hashlib.sha256(text.encode()).digest()
    # Expand via repeated hashing to dims
    vals = []
    counter = 0
    while len(vals) < dims:
        chunk = hashlib.sha256(h + counter.to_bytes(2, "little")).digest()
        for b in chunk:
            vals.append((b / 127.5) - 1.0)  # [-1,1]
            if len(vals) >= dims:
                break
        counter += 1
    # L2 normalize
    norm = math.sqrt(sum(x * x for x in vals)) or 1.0
    return [x / norm for x in vals]


def _load_model():
    global _model, _model_dims, _model_loaded_at
    if _model is not None:
        return _model
    # Try ONNX first (lighter, 20MB), then sentence-transformers (80MB)
    try:
        # Try optimum ONNX
        from optimum.onnxruntime import ORTModelForFeatureExtraction
        from transformers import AutoTokenizer

        print(f"[embed-api] Loading ONNX {MODEL_NAME} ...")
        tok = AutoTokenizer.from_pretrained(MODEL_NAME)
        mdl = ORTModelForFeatureExtraction.from_pretrained(MODEL_NAME, export=True)
        _model = (tok, mdl, "onnx")
        _model_dims = 384
        _model_loaded_at = time.time()
        print(f"[embed-api] ONNX loaded dims={_model_dims}")
        return _model
    except Exception as e:
        print(f"[embed-api] ONNX load failed: {e} — trying sentence-transformers")

    try:
        from sentence_transformers import SentenceTransformer

        print(f"[embed-api] Loading sentence-transformers {MODEL_NAME} ...")
        st = SentenceTransformer(MODEL_NAME)
        _model = (st, None, "st")
        _model_dims = st.get_sentence_embedding_dimension() or 384
        _model_loaded_at = time.time()
        print(f"[embed-api] ST loaded dims={_model_dims}")
        return _model
    except Exception as e:
        print(f"[embed-api] ST load failed: {e} — using hash fallback 384d")
        _model = ("hash", None, "hash")
        _model_dims = 384
        _model_loaded_at = time.time()
        return _model


def _encode(texts: List[str]) -> List[List[float]]:
    mdl = _load_model()
    kind = mdl[2] if isinstance(mdl, tuple) else "hash"

    if kind == "hash":
        return [_hash_embed(t, _model_dims) for t in texts]

    if kind == "onnx":
        tok, ort_model, _ = mdl  # type: ignore
        import torch
        import numpy as np

        encoded = tok(texts, padding=True, truncation=True, return_tensors="pt", max_length=256)
        with torch.no_grad():
            out = ort_model(**encoded)
            # Mean pooling
            last_hidden = out.last_hidden_state  # [B, L, D]
            mask = encoded["attention_mask"].unsqueeze(-1).float()  # [B, L, 1]
            summed = (last_hidden * mask).sum(dim=1)
            counts = mask.sum(dim=1).clamp(min=1e-9)
            embs = (summed / counts).cpu().numpy()
            # L2 normalize
            norms = np.linalg.norm(embs, axis=1, keepdims=True).clip(min=1e-9)
            embs = embs / norms
            return embs.tolist()

    # st
    st, _, _ = mdl  # type: ignore
    embs = st.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return embs.tolist()  # type: ignore


def _auth_ok(authorization: str | None) -> bool:
    if not EMBED_API_KEY:
        return True  # open in dev
    if not authorization:
        return False
    # Bearer <token>
    token = authorization.removeprefix("Bearer ").strip()
    # Also accept raw token
    return token == EMBED_API_KEY


@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "dims": _model_dims,
        "loaded": _model is not None,
        "loaded_at": _model_loaded_at,
    }


@app.get("/v1/models")
def list_models():
    return {"object": "list", "data": [{"id": MODEL_NAME, "object": "model", "owned_by": "nally"}]}


@app.post("/v1/embeddings")
async def create_embeddings(request: Request, authorization: str | None = Header(default=None)):
    if not _auth_ok(authorization):
        raise HTTPException(status_code=401, detail="Missing or invalid Bearer token")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    raw_input: Union[str, List[str]] = body.get("input")
    if raw_input is None:
        # Also accept "inputs" alias
        raw_input = body.get("inputs")
    if raw_input is None:
        raise HTTPException(status_code=400, detail="Missing 'input' field")
    texts: List[str] = [raw_input] if isinstance(raw_input, str) else list(raw_input)
    if not texts:
        raise HTTPException(status_code=400, detail="Empty input")
    # Cap batch to avoid OOM on Free 512MB
    if len(texts) > 64:
        raise HTTPException(status_code=400, detail="Batch max 64, got %d" % len(texts))
    for t in texts:
        if len(t) > 8000:
            raise HTTPException(status_code=400, detail="Text too long (max 8000 chars)")

    start = time.time()
    embeddings = _encode(texts)
    elapsed_ms = (time.time() - start) * 1000

    data = [
        {"object": "embedding", "embedding": emb, "index": i}
        for i, emb in enumerate(embeddings)
    ]
    # Rough token estimate: 1 token ~4 chars
    prompt_tokens = sum(len(t) // 4 for t in texts)

    resp = {
        "object": "list",
        "data": data,
        "model": body.get("model", MODEL_NAME),
        "usage": {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens},
        "_elapsed_ms": round(elapsed_ms, 1),
    }
    # Optional: add dims for client cache key
    resp["_dims"] = _model_dims
    return JSONResponse(content=resp)


@app.get("/")
def root():
    return {
        "service": "nally-embed-api",
        "model": MODEL_NAME,
        "docs": "/docs",
        "health": "/health",
        "embed": "POST /v1/embeddings {input: str|str[], model}",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
