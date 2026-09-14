# Embed API — separate Render Free instance (MiniLM ONNX 20MB, 384d, 120MB RAM)
# NALLY main stays lean (<300MB free) — this holds the model.
# Build: docker build -t nally-embed ./embed-api
# Run:   docker run -p 8000:8000 -e EMBED_MODEL=all-MiniLM-L6-v2 -e EMBED_API_KEY=secret nally-embed
# Deploy on Render Free: new Web Service, Root Directory: embed-api, Dockerfile: embed-api/Dockerfile

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/app/.cache/hf \
    TRANSFORMERS_CACHE=/app/.cache/hf \
    EMBED_MODEL=all-MiniLM-L6-v2

WORKDIR /app

# System deps (build once, cached)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
  && rm -rf /var/lib/apt/lists/*

# Python deps — onnxruntime is lighter than torch (120MB RAM vs 400MB)
# Keep image <350MB for Free tier. No torch here.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake model into image so Free ephemeral disk survives restarts
# (download at build, not at runtime)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('all-MiniLM-L6-v2')" || echo "bake skipped — will lazy-load with hash fallback"

COPY app.py ./app.py

RUN mkdir -p /app/.cache/hf

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=20s \
  CMD curl -fsS http://localhost:${PORT:-8000}/health || exit 1

CMD ["python", "app.py"]
