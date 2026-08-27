FROM python:3.12-slim AS builder

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


FROM python:3.12-slim AS runtime

# Create non-root user
RUN groupadd -r nally && useradd -r -g nally -d /app -s /sbin/nologin nally

WORKDIR /app

# Copy installed deps from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY nally/ ./nally/
COPY web/ ./web/
COPY skills/ ./skills/
COPY main.py .
COPY run_tg_user.py run_bot_standalone.py run_tg_call.py ./

# Create data directories (generated is needed for image gen output)
RUN mkdir -p data/generated logs && chown -R nally:nally /app

USER nally

# Render expects 10000 by default (https://render.com/docs/web-services#port-binding)
# EXPOSE is documentary, but keep 10000 to match Render's PORT. Also bind to 0.0.0.0.
EXPOSE 10000

HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=5 \
    CMD python -c "import os, httpx; p=os.getenv('PORT','10000'); import time; time.sleep(2); httpx.get(f'http://localhost:{p}/health/live', timeout=5.0).raise_for_status()"

CMD ["python", "main.py"]
