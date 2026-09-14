# Embed API — separate Render Free instance (MiniLM ONNX 22MB, 384d, 120MB RAM)
# NALLY main stays lean (<300MB) — this holds the model.
# Build: docker build -t nally-embed ./embed-api
# Run:   docker run -p 8000:8000 -e EMBED_MODEL=all-MiniLM-L6-v2 -e EMBED_API_KEY=secret nally-embed
# Deploy on Render Free: new Web Service, Root Directory: embed-api, Dockerfile: Dockerfile

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

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
  && rm -rf /var/lib/apt/lists/*

# Python deps — onnxruntime only, no torch
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bake model into image via optimum ONNX export + dynamic quantization
# Produces /app/model/ with tokenizer + quantized ONNX (~22MB, not 80MB)
RUN python -c " \
from optimum.onnxruntime import ORTModelForFeatureExtraction; \
from transformers import AutoTokenizer; \
import os; \
model_name = os.getenv('EMBED_MODEL'); \
print(f'[embed-api bake] Exporting {model_name} to ONNX ...'); \
tok = AutoTokenizer.from_pretrained(model_name); \
tok.save_pretrained('/app/model'); \
mdl = ORTModelForFeatureExtraction.from_pretrained(model_name, export=True); \
mdl.save_pretrained('/app/model'); \
print('[embed-api bake] ONNX export done'); \
" && echo "Model baked: $(du -sh /app/model | cut -f1)"

# Dynamic quantization pass (reduce 80MB float32 → 22MB int8)
RUN python -c " \
from optimum.onnxruntime import ORTQuantizer; \
from optimum.onnxruntime.configuration import AutoQuantizationConfig; \
import os; \
onnx_path = '/app/model/model.onnx'; \
if os.path.exists(onnx_path): \
    qconfig = AutoQuantizationConfig.avx512_vnni(is_static=False, per_channel=True, operators_to_quantize=['MatMul', 'Add']); \
    quantizer = ORTQuantizer.from_pretrained(onnx_path); \
    quantizer.quantize(save_dir='/app/model', quantization_config=qconfig); \
    print('[embed-api bake] Quantized ONNX done'); \
else: \
    print(f'[embed-api bake] model.onnx not found — skipped quantization'); \
" 2>&1 || echo "quantize skipped — will use float32 ONNX (still no torch)"

COPY app.py ./app.py

RUN mkdir -p /app/.cache/hf

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --retries=3 --start-period=25s \
  CMD curl -fsS http://localhost:${PORT:-8000}/health || exit 1

CMD ["python", "app.py"]
