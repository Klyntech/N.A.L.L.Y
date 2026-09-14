# NALLY Embed API — Free Tier Separate Instance

**22MB MiniLM ONNX (int8 quantized), 384d, 120MB RAM** — keeps **NALLY main (<300MB)** lean on Render Free 512MB.

NALLY `nally/memory/embeddings.py` calls this via `NALLY_EMBED_BASE_URL` (`POST /v1/embeddings` OpenAI-compatible).

## Architecture

- **No torch** — pure `onnxruntime` + `transformers` tokenizer at runtime
- Model baked into image at build via `optimum-cli` ONNX export + dynamic quantization (80MB float32 → 22MB int8)
- Falls back to deterministic hash 384d if ONNX model can't load (dev/testing)

## Deploy on Render (Free)

1. Create **new Web Service** → connect `N.A.L.L.Y` repo → **Root Directory:** `embed-api` → **Dockerfile:** `Dockerfile`
2. **Plan:** Free (512MB) — MiniLM ONNX fits. Don't use Gemma 600MB on Free.
3. Env vars on embed service:
   ```
   EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2
   EMBED_API_KEY=your-long-random-internal-token  # same as NALLY_INTERNAL_TOKEN
   PORT=10000  # Render injects PORT, app reads it
   ```
4. On **NALLY service** set:
   ```
   NALLY_EMBED_PROVIDER=embed_api
   NALLY_EMBED_BASE_URL=https://your-embed-free.onrender.com  # no /v1 suffix OK, it adds /v1/embeddings
   NALLY_EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2
   NALLY_EMBED_API_KEY=your-long-random-internal-token  # same token
   NALLY_EMBED_DIMS=384
   ```
5. Health: `GET https://your-embed-free.onrender.com/health` → `{"status":"ok","model":"...","dims":384,"backend":"onnx"}`

## Local

```bash
docker build -t nally-embed ./embed-api
docker run -p 8000:8000 -e EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2 -e EMBED_API_KEY=dev nally-embed
curl -X POST http://localhost:8000/v1/embeddings -H "Content-Type: application/json" -H "Authorization: Bearer dev" -d '{"input":"hello world","model":"sentence-transformers/all-MiniLM-L6-v2"}'
curl http://localhost:8000/health
```

Or via docker compose (NALLY + embed together):
```bash
docker compose --profile with-embed up -d
```

## Free Tier Notes

- **Sleep:** both NALLY + embed Free sleep after 15m idle → first `remember()` after wake = 8-12s cold start (acceptable, background reflection).
- **Hours:** 750h/month combined — 2 Free services ≈ 375h each if 24/7; use `profiles: [with-embed]` locally, or let embed sleep and NALLY falls back to keyword FTS when `POST` fails (graceful fallback in `embeddings.py:embed_texts` returns `None`).
- **Batch cap:** 64 texts per request (OOM guard `app.py`), each `max 8000 chars`.
- **Fallback:** if model can't load at build (no internet), service uses deterministic hash 384d — still returns embeddings so NALLY doesn't break (quality lower, but recall works).

## Health Response

```json
{
  "status": "ok",
  "model": "sentence-transformers/all-MiniLM-L6-v2",
  "dims": 384,
  "backend": "onnx",
  "loaded": true,
  "loaded_at": 1694600000.0
}
```

`backend` can be: `onnx` (production), `st` (sentence-transformers fallback), `hash` (deterministic pseudo-embed).

## Upgrade Paths

- Want better quality on same 384d but still Free? Stay MiniLM.
- Want 768d Gemma/bge? Move embed instance to **Standard 2GB** — then set `EMBED_MODEL=BAAI/bge-small-en-v1.5` or `EmbeddingGemma` and add `torch` to `requirements.txt`.
