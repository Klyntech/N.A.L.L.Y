# Embed API — separate Render Free instance (MiniLM ONNX 22MB, 384d, 120MB RAM)
# NALLY main stays lean (<300MB) — this holds the model.
# Build: docker build -t nally-embed ./embed-api
# Run:   docker run -p 8000:8000 -e EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2 -e EMBED_API_KEY=secret nally-embed
# Deploy on Render Free: new Web Service, Root Directory: embed-api, Dockerfile: Dockerfile

# ── Stage 1: Builder — export ONNX (needs torch + optimum, discarded after) ──
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/hf \
    TRANSFORMERS_CACHE=/app/.cache/hf \
    EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
    EMBED_MODEL_PATH=/app/model

WORKDIR /app

COPY requirements-builder.txt .
RUN pip install --no-cache-dir -r requirements-builder.txt

COPY bake.py ./bake.py
RUN python bake.py

# ── Stage 2: Runtime — onnxruntime only, no torch, no optimum ──
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/hf \
    TRANSFORMERS_CACHE=/app/.cache/hf \
    EMBED_MODEL=sentence-transformers/all-MiniLM-L6-v2 \
    EMBED_MODEL_PATH=/app/model \
    EMBED_DIMS=384

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
  && rm -rf /var/lib/apt/lists/*

# Runtime deps — no torch, no optimum
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy baked model from builder
COPY --from=builder /app/model /app/model

COPY app.py ./app.py

RUN mkdir -p /app/.cache/hf

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=25s \
  CMD curl -fsS http://localhost:${PORT:-8000}/health || exit 1

CMD ["python", "app.py"]
