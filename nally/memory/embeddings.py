"""Embedding provider for NALLY memory — Free-tier separate instance.

NALLY stays lean (<300MB free) — no torch on main app.
Embedding model lives on a separate Render Free instance (MiniLM ONNX 20MB, 384d, ~120MB RAM)
exposed as OpenAI-compatible POST /v1/embeddings.

Env:
  NALLY_EMBED_PROVIDER=none|embed_api|openai  (default none = keyword FTS only)
  NALLY_EMBED_BASE_URL=https://your-embed-free.onrender.com/v1
  NALLY_EMBED_MODEL=all-MiniLM-L6-v2  (384d)
  NALLY_EMBED_API_KEY=...  (Bearer, use NALLY_INTERNAL_TOKEN)
  NALLY_EMBED_TIMEOUT=15
  NALLY_EMBED_CACHE_TTL=3600

Free-tier note: embed_api Free 512MB can only run MiniLM ONNX 20MB (384d).
Gemma 600MB / bge 133MB need Starter+ — don't deploy those on Free.
Keep NALLY main image lean: no sentence-transformers/torch here.
"""

import hashlib
import logging
import time
from typing import Dict, List, Optional

logger = logging.getLogger("nally.embeddings")

# In-memory cache: text_hash -> (embedding, expires_at)
_cache: Dict[str, tuple] = {}


def _cache_key(text: str, model: str) -> str:
    return hashlib.sha256(f"{model}:::{text}".encode()).hexdigest()


def _cache_get(key: str) -> Optional[List[float]]:
    try:
        from ..config import NALLY_EMBED_CACHE_TTL

        ttl = NALLY_EMBED_CACHE_TTL
    except Exception:
        ttl = 3600
    item = _cache.get(key)
    if not item:
        return None
    emb, exp = item
    if time.time() > exp:
        _cache.pop(key, None)
        return None
    return emb


def _cache_set(key: str, emb: List[float]):
    try:
        from ..config import NALLY_EMBED_CACHE_TTL

        ttl = NALLY_EMBED_CACHE_TTL
    except Exception:
        ttl = 3600
    _cache[key] = (emb, time.time() + ttl)
    # Bound cache size (LRU approx): keep last 2000
    if len(_cache) > 2000:
        # drop oldest 500
        oldest = sorted(_cache.items(), key=lambda kv: kv[1][1])[:500]
        for k, _ in oldest:
            _cache.pop(k, None)


def _embed_via_api(texts: List[str], model: str, base_url: str, api_key: str, timeout: int) -> Optional[List[List[float]]]:
    """Call OpenAI-compatible POST /v1/embeddings. Returns list of float[] or None on failure."""
    if not base_url or not texts:
        return None
    # Lazy import so main app doesn't require httpx if unused
    try:
        import httpx
    except ImportError:
        logger.debug("httpx not available for embeddings")
        return None

    url = base_url.rstrip("/") + "/v1/embeddings"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    payload = {"input": texts, "model": model}
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=timeout)
        if resp.status_code != 200:
            logger.warning(f"Embed API {resp.status_code}: {resp.text[:200]}")
            return None
        data = resp.json()
        # OpenAI shape: {data: [{embedding: [...]}, ...]}
        items = data.get("data", [])
        if not items:
            # Alt shape: {embeddings: [[...]]}
            alt = data.get("embeddings")
            if alt:
                return alt
            return None
        # Sort by index to preserve input order
        items_sorted = sorted(items, key=lambda x: x.get("index", 0))
        return [it["embedding"] for it in items_sorted]
    except Exception as e:
        logger.warning(f"Embed API failed: {e}")
        return None


def embed_texts(texts: List[str]) -> Optional[List[List[float]]]:
    """Embed a batch of texts via configured provider. Returns None if disabled/failed (caller falls back to FTS)."""
    try:
        from ..config import (
            NALLY_EMBED_BASE_URL,
            NALLY_EMBED_MODEL,
            NALLY_EMBED_PROVIDER,
            NALLY_EMBED_TIMEOUT,
            NALLY_EMBED_API_KEY,
        )
    except Exception:
        return None

    provider = (NALLY_EMBED_PROVIDER or "none").lower()
    if provider == "none" or not provider:
        return None
    if provider not in ("embed_api", "openai"):
        logger.debug(f"Unknown embed provider {provider}")
        return None

    base_url = NALLY_EMBED_BASE_URL
    model = NALLY_EMBED_MODEL or "all-MiniLM-L6-v2"
    api_key = NALLY_EMBED_API_KEY
    timeout = NALLY_EMBED_TIMEOUT or 15

    if not base_url:
        logger.debug("NALLY_EMBED_BASE_URL not set — skipping embed")
        return None

    # Serve from cache where possible
    uncached_texts: List[str] = []
    uncached_idx: List[int] = []
    results: List[Optional[List[float]]] = [None] * len(texts)

    for i, t in enumerate(texts):
        k = _cache_key(t, model)
        cached = _cache_get(k)
        if cached is not None:
            results[i] = cached
        else:
            uncached_texts.append(t)
            uncached_idx.append(i)

    if uncached_texts:
        fetched = _embed_via_api(uncached_texts, model, base_url, api_key, timeout)
        if fetched is None:
            # If any batch fails, return None so caller falls back — but preserve cached hits for future
            # Return partial if we had cached hits, else None
            if any(r is not None for r in results):
                # Fill fetched where possible (none)
                return [r for r in results if r is not None]  # partial not aligned — caller should handle None
            return None
        for idx, emb in zip(uncached_idx, fetched):
            results[idx] = emb
            _cache_set(_cache_key(texts[idx], model), emb)

    # All filled?
    if any(r is None for r in results):
        return None
    return results  # type: ignore


def embed_one(text: str) -> Optional[List[float]]:
    """Embed single text, cached."""
    res = embed_texts([text])
    if res and len(res) == 1:
        return res[0]
    return None


def cosine_sim(a: List[float], b: List[float]) -> float:
    """Cosine similarity, safe for zero vectors."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def clear_cache():
    _cache.clear()


def cache_info() -> dict:
    return {"size": len(_cache)}
