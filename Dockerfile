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
COPY main.py .

# Create data directory
RUN mkdir -p data logs && chown -R nally:nally /app

USER nally

EXPOSE 5000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:5000/health').raise_for_status()"

CMD ["python", "main.py"]
