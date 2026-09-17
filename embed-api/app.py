"""Embed API — separate Render Free instance (MiniLM ONNX 22MB, 384d, 120MB RAM).

NALLY main stays lean (<300MB) — no torch here. This service holds the model.

POST /v1/embeddings  {input: str | str[], model: "all-MiniLM-L6-v2"}
  → {object:"list", data:[{object:"embedding", embedding:[...384], index:0}], model, usage:{prompt_tokens, total_tokens}}

GET /health → {"status":"ok", "model":"...", "dims":384}
GET /v1/models → {"data":[{"id":"all-MiniLM-L6-v2"}]}

Free-tier notes:
- Model baked into image at build (not downloaded at runtime) — ephemeral disk survives via image.
- ONNX quantized via optimum → ~22MB int8, RAM ~120MB. No torch.
- If no ONNX, falls back to hash 384d (dev/testing, still returns valid vectors).
- Auth: optional Bearer NALLY_INTERNAL_TOKEN (set EMBED_API_KEY). If unset, open (dev only).

Run:
  docker build -t nally-embed ./embed-api
  docker run -p 8000:8000 -e EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2 nally-embed
  curl -X POST http://localhost:8000/v1/embeddings -H "Content-Type: application/json" -d '{"input":"hello world","model":"all-MiniLM-L6-v2"}'

Deploy on Render Free: build this Dockerfile as separate Web Service (port 8000), set EMBED_MODEL env.
"""

import asyncio
import gc
import os
import threading
import time
from contextlib import asynccontextmanager
from typing import List, Optional, Union

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse

try:
    import resource as _resource  # stdlib, Linux only — RSS logging
except ImportError:  # Windows local dev
    _resource = None


def _rss_mb() -> float:
    """Current peak RSS in MB (0.0 when unavailable)."""
    try:
        if _resource is None:
            return 0.0
        return _resource.getrusage(_resource.RUSAGE_SELF).ru_maxrss / 1024.0
    except Exception:
        return 0.0


MODEL_NAME = os.getenv("EMBED_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
MODEL_PATH = os.getenv("EMBED_MODEL_PATH", "/app/model")
EMBED_API_KEY = os.getenv("EMBED_API_KEY", "") or os.getenv("NALLY_INTERNAL_TOKEN", "")
PORT = int(os.getenv("PORT", "8000"))

# Free-tier batch cap: bounds per-request peak RSS on 512MB. Nally's client
# chunks to the same value — keep them in sync.
MAX_BATCH = int(os.getenv("EMBED_MAX_BATCH", "32"))

# Optional: Hugging Face cache inside container (baked at build)
os.environ.setdefault("HF_HOME", "/app/.cache/hf")
os.environ.setdefault("TRANSFORMERS_CACHE", "/app/.cache/hf")

# Serialize inference: one batch at a time. Overlapping batches multiply peak
# RSS nondeterministically (the OOM pattern). Requests queue instead of dying.
_infer_sem: Optional[asyncio.Semaphore] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _infer_sem
    _infer_sem = asyncio.Semaphore(1)

    # Pre-warm the model in the background AFTER the port is bound, so the
    # first real request never pays the load spike inside its own timeout.
    # Render healthchecks hit /health (cheap) while this loads.
    def _prewarm():
        try:
            time.sleep(5)  # let startup/health settle first
            _load_model()
            print(f"[embed-api] pre-warm done backend={_model_backend} rss={_rss_mb():.0f}MB")
        except Exception as e:
            print(f"[embed-api] pre-warm failed (lazy load on first request): {e}")

    threading.Thread(target=_prewarm, daemon=True, name="prewarm").start()
    yield


app = FastAPI(title="NALLY Embed API", version="2.1.0", lifespan=lifespan)

# Lazy model — load on first request to keep healthcheck fast
_model = None  # type: tuple | None
_model_dims = 384
_model_loaded_at: Optional[float] = None
_model_backend: str = "unknown"  # onnx | hash


# ── Hash fallback (deterministic 384d, no quality guarantee) ────────
def _hash_embed(text: str, dims: int = 384) -> List[float]:
    import hashlib
    import math

    h = hashlib.sha256(text.encode()).digest()
    vals: List[float] = []
    counter = 0
    while len(vals) < dims:
        chunk = hashlib.sha256(h + counter.to_bytes(2, "little")).digest()
        for b in chunk:
            vals.append((b / 127.5) - 1.0)
            if len(vals) >= dims:
                break
        counter += 1
    norm = math.sqrt(sum(x * x for x in vals)) or 1.0
    return [x / norm for x in vals]


# ── ONNX model loading (no torch anywhere) ──────────────────────────
def _load_model():
    """Load ONNX model + tokenizer from baked path. Falls back to hash."""
    global _model, _model_dims, _model_loaded_at, _model_backend

    if _model is not None:
        return _model

    # Try loading from baked path (Dockerfile bakes at build time)
    try:
        import numpy as np
        import onnxruntime as ort
        from transformers import AutoTokenizer

        # Check baked path exists — try multiple locations
        candidates = [
            os.path.join(MODEL_PATH, "model_quantized.onnx"),
            os.path.join(MODEL_PATH, "model.onnx"),
            os.path.join(MODEL_PATH, "onnx", "model.onnx"),
            os.path.join(MODEL_PATH, "onnx", "model_q4.onnx"),
        ]
        onnx_file = None
        for c in candidates:
            if os.path.exists(c):
                onnx_file = c
                break
        if not onnx_file:
            raise FileNotFoundError(f"No ONNX model found at {MODEL_PATH}")

        print(f"[embed-api] Loading ONNX from {onnx_file} ...")
        tok = AutoTokenizer.from_pretrained(MODEL_PATH)
        # Free-tier (512MB) tuning: single-threaded execution + no arena/memory
        # pattern. Slightly slower per request, but peak RSS stays bounded so
        # the container stops getting OOM-killed on large batches.
        so = ort.SessionOptions()
        so.intra_op_num_threads = 1
        so.inter_op_num_threads = 1
        so.enable_mem_pattern = False
        so.enable_cpu_mem_arena = False
        sess = ort.InferenceSession(onnx_file, sess_options=so, providers=["CPUExecutionProvider"])
        _model = (tok, sess, "onnx")
        _model_dims = sess.get_inputs()[0].shape[-1] if sess.get_inputs() else 384
        # Dynamic axes return string names (e.g. "sequence_length") — default to 384
        if not isinstance(_model_dims, int):
            _model_dims = 384
        _model_loaded_at = time.time()
        _model_backend = "onnx"
        print(f"[embed-api] ONNX loaded dims={_model_dims} backend=onnxruntime")
        return _model
    except Exception as e:
        print(f"[embed-api] ONNX load failed: {e} — falling back to hash")

    try:
        # Last resort: try sentence-transformers (needs torch — should not happen on Free)
        from sentence_transformers import SentenceTransformer

        print(f"[embed-api] Trying sentence-transformers {MODEL_NAME} (needs torch) ...")
        st = SentenceTransformer(MODEL_NAME)
        _model = (st, None, "st")
        _model_dims = st.get_sentence_embedding_dimension() or 384
        _model_loaded_at = time.time()
        _model_backend = "st"
        print(f"[embed-api] ST loaded dims={_model_dims}")
        return _model
    except Exception as e:
        print(f"[embed-api] ST load failed: {e} — using hash fallback 384d")
        _model = ("hash", None, "hash")
        _model_dims = 384
        _model_loaded_at = time.time()
        _model_backend = "hash"
        return _model


# ── Encoding (pure numpy, no torch) ─────────────────────────────────
def _encode(texts: List[str]) -> List[List[float]]:
    """Encode texts to 384d L2-normalized vectors. No torch."""
    mdl = _load_model()
    kind = mdl[2] if isinstance(mdl, tuple) else "hash"

    if kind == "hash":
        return [_hash_embed(t, _model_dims) for t in texts]

    if kind == "onnx":
        tok, sess, _ = mdl
        import numpy as np

        # Tokenize (no torch tensors — just numpy).
        # max_length=128: memory key/value texts are short; halves activation
        # memory vs 256 with negligible quality impact on Free tier.
        encoded = tok(
            texts,
            padding=True,
            truncation=True,
            max_length=128,
            return_tensors="np",
        )

        # ONNX inference
        input_names = [inp.name for inp in sess.get_inputs()]
        feed = {}
        for name in input_names:
            if name in encoded:
                feed[name] = encoded[name]

        outputs = sess.run(None, feed)
        last_hidden = outputs[0]  # [B, L, D]

        # Mean pooling with attention mask
        attention_mask = encoded.get("attention_mask", np.ones(last_hidden.shape[:2], dtype=np.float32))
        mask = attention_mask[:, :, np.newaxis].astype(np.float32)  # [B, L, 1]
        summed = (last_hidden * mask).sum(axis=1)  # [B, D]
        counts = mask.sum(axis=1).clip(min=1e-9)  # [B, 1]
        embs = summed / counts  # [B, D]

        # L2 normalize
        norms = np.linalg.norm(embs, axis=1, keepdims=True).clip(min=1e-9)
        embs = embs / norms
        return embs.tolist()

    # st (sentence-transformers with torch — fallback only)
    st, _, _ = mdl
    embs = st.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return embs.tolist()


# ── Auth ─────────────────────────────────────────────────────────────
def _auth_ok(authorization: Optional[str]) -> bool:
    if not EMBED_API_KEY:
        return True  # open in dev
    if not authorization:
        return False
    token = authorization.removeprefix("Bearer ").strip()
    return token == EMBED_API_KEY


# ── Routes ───────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {
        "status": "ok",
        "model": MODEL_NAME,
        "dims": _model_dims,
        "backend": _model_backend,
        "loaded": _model is not None,
        "loaded_at": _model_loaded_at,
    }


@app.get("/v1/models")
def list_models():
    return {"object": "list", "data": [{"id": MODEL_NAME, "object": "model", "owned_by": "nally"}]}


@app.post("/v1/embeddings")
async def create_embeddings(request: Request, authorization: Optional[str] = Header(default=None)):
    if not _auth_ok(authorization):
        raise HTTPException(status_code=401, detail="Missing or invalid Bearer token")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    raw_input: Union[str, List[str]] = body.get("input")
    if raw_input is None:
        raw_input = body.get("inputs")
    if raw_input is None:
        raise HTTPException(status_code=400, detail="Missing 'input' field")
    texts: List[str] = [raw_input] if isinstance(raw_input, str) else list(raw_input)
    if not texts:
        raise HTTPException(status_code=400, detail="Empty input")
    # Cap batch to avoid OOM on Free 512MB (keep in sync with Nally client)
    if len(texts) > MAX_BATCH:
        raise HTTPException(status_code=400, detail="Batch max %d, got %d" % (MAX_BATCH, len(texts)))
    for t in texts:
        if len(t) > 8000:
            raise HTTPException(status_code=400, detail="Text too long (max 8000 chars)")

    start = time.time()
    rss_before = _rss_mb()
    # Serialize + run off the event loop: _encode is blocking CPU work and
    # must never stall concurrent requests (health, parallel recalls).
    sem = _infer_sem or asyncio.Semaphore(1)
    async with sem:
        embeddings = await asyncio.to_thread(_encode, texts)
    try:
        gc.collect()  # return arena/peak pages promptly on long-lived process
    except Exception:
        pass
    elapsed_ms = (time.time() - start) * 1000
    print(f"[embed-api] batch={len(texts)} elapsed_ms={elapsed_ms:.0f} rss={_rss_mb():.0f}MB (+{_rss_mb()-rss_before:.0f}MB) backend={_model_backend}")

    data = [
        {"object": "embedding", "embedding": emb, "index": i}
        for i, emb in enumerate(embeddings)
    ]
    prompt_tokens = sum(len(t) // 4 for t in texts)

    resp = {
        "object": "list",
        "data": data,
        "model": body.get("model", MODEL_NAME),
        "usage": {"prompt_tokens": prompt_tokens, "total_tokens": prompt_tokens},
        "_elapsed_ms": round(elapsed_ms, 1),
        "_dims": _model_dims,
        "_backend": _model_backend,
    }
    return JSONResponse(content=resp)


@app.get("/")
def root():
    return {
        "service": "nally-embed-api",
        "version": "2.1.0",
        "model": MODEL_NAME,
        "backend": _model_backend,
        "docs": "/docs",
        "health": "/health",
        "embed": "POST /v1/embeddings {input: str|str[], model}",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
