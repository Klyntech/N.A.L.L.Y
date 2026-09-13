# Deployment

## Docker (Recommended)

### Build

```bash
docker build -t nally:latest .
```

The Dockerfile uses a multi-stage build:
- **Builder stage**: Installs Python dependencies
- **Runtime stage**: Copies deps + app code, creates non-root user, sets up health check

### Run

```bash
docker run -d \
  --name nally \
  -p 5000:5000 \
  -v nally-data:/app/data \
  -e NALLY_PROVIDER=opencode \
  -e OPENCODE_API_KEY=sk-... \
  -e NALLY_ACCESS_TOKEN=your-secret \
  --restart unless-stopped \
  nally:latest
```

### Docker Compose

The repo ships a `docker-compose.yml` with an `app` service (builds the Dockerfile)
and an optional `redis` service gated behind the `with-redis` profile:

```bash
docker compose up -d          # app only
docker compose --profile with-redis up -d   # app + redis
```

It maps `${PORT:-5000}:5000`, loads `.env` via `env_file`, mounts `nally_data`
and `nally_logs` volumes, and restarts unless stopped.

### Environment Variables for Production

```env
# Required
NALLY_PROVIDER=opencode
OPENCODE_API_KEY=sk-...
NALLY_ACCESS_TOKEN=generate-a-long-random-string

# Security
ALLOWED_ORIGINS=https://your-domain.com
RATE_LIMIT_ENABLED=true
RATE_LIMIT_RPM=30
RATE_LIMIT_BURST=60

# Data store — SQLite is the datastore (there is no nally/db/ PostgreSQL/Redis
# adapter package). DATABASE_URL may be a SQLite path or a Turso/LibSQL URL.
# PostgreSQL and Redis URLs are ONLY read by the /health probes (nally/web/health.py)
# to report reachability — they are not used as the application datastore.
DATABASE_URL=data/nally.db
# DATABASE_URL=postgresql://user:pass@host:5432/nally   # health-probe check only
# REDIS_URL=redis://host:6379                           # health-probe check only
```

## Systemd (Linux)

Create `/etc/systemd/system/nally.service`:

```ini
[Unit]
Description=Nally AI Assistant
After=network.target

[Service]
Type=simple
User=nally
WorkingDirectory=/opt/nally
ExecStart=/opt/nally/venv/bin/python main.py --port 5000
Restart=always
RestartSec=5
Environment=NALLY_PROVIDER=opencode
Environment=OPENCODE_API_KEY=sk-...
Environment=NALLY_ACCESS_TOKEN=your-secret

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable nally
sudo systemctl start nally
sudo systemctl status nally
```

## Reverse Proxy

### Nginx

```nginx
server {
    listen 80;
    server_name nally.your-domain.com;

    location / {
        proxy_pass http://localhost:5000;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # SSE support — disable buffering
    location /api/chat {
        proxy_pass http://localhost:5000;
        proxy_http_version 1.1;
        proxy_set_header Connection '';
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding off;
    }

    # WebSocket support
    location /ws/ {
        proxy_pass http://localhost:5000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

### Caddy

```
nally.your-domain.com {
    reverse_proxy localhost:5000
}
```

Caddy automatically handles SSE and WebSocket upgrades.

## Health Checks

For load balancers and orchestrators:

| Endpoint | Purpose | Auth |
|----------|---------|------|
| `/health` | Full health (DB, Redis, tools) | No |
| `/health/live` | Liveness probe | No |
| `/health/ready` | Readiness probe | No |

Kubernetes example:

```yaml
livenessProbe:
  httpGet:
    path: /health/live
    port: 5000
  initialDelaySeconds: 10
  periodSeconds: 30

readinessProbe:
  httpGet:
    path: /health/ready
    port: 5000
  initialDelaySeconds: 5
  periodSeconds: 10
```

## GitHub Container Registry

CI publishes Docker images to GHCR (`ghcr.io/klyntech/nally`) whenever a `v*` git tag is pushed (`.github/workflows/publish.yml`, and available manually via `workflow_dispatch`). The workflow tags images with `type=semver` (e.g. `v1.2.0`, `v1.2`) plus the commit SHA.

> **Note**: no git tags exist in the repository yet, so no image has been published so far. Once a `v*` tag is created and pushed, the image will appear at:

```bash
docker pull ghcr.io/klyntech/nally:latest
```

Tags:
- `latest` — latest stable
- `v1.2.0` — specific version
- `<sha>` — commit SHA

## Monitoring

- Logs: `logs/` directory (rotating, 1MB max, 7-day retention)
- Execution traces: `GET /api/traces` (browse recent runs)
- Run details: `GET /api/trace/{run_id}` (full span tree)
- Tool receipts: JSONL files in `data/` (auto-rotate at 10MB)
