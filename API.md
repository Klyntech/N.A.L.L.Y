# API Reference

Nally exposes a REST API with SSE streaming and WebSocket support. Most endpoints require Bearer token auth; the exceptions are health endpoints, OAuth callbacks, `GET /api/status`, and the two Telegram message/approve endpoints (`POST /api/telegram/message`, `POST /api/telegram/approve`) — all of which have no auth dependency. Each endpoint's auth requirement is noted below.

## Authentication

Include the token in the `Authorization` header:

```
Authorization: Bearer <NALLY_ACCESS_TOKEN>
```

Token is validated using constant-time comparison (`hmac.compare_digest`).

## Endpoints

### Chat

#### `POST /api/chat`

Send a message and receive a streaming SSE response.

**Request:**
```json
{
  "message": "What's the weather like?",
  "session_id": "web:default",
  "tab_id": "optional-tab-id"
}
```

**Response** (SSE stream):
```
data: {"type": "run_id", "run_id": "abc123"}

data: {"type": "stream_chunk", "text": "Let me check"}

data: {"type": "tool_call", "tool": "web_search", "args": {"query": "weather"}}

data: {"type": "tool_result", "tool": "web_search", "result": "..."}

data: {"event": "done"}
```

**SSE Event Types:**

| Event | Payload | Description |
|-------|---------|-------------|
| `run_id` | `{run_id}` | Unique ID for this execution trace |
| `stream_chunk` | `{text}` | Partial text from LLM |
| `done` | `{}` | Response complete (`{"event": "done"}` terminal event) |
| `thought` | `{text}` | Internal reasoning (if thinking enabled) |
| `tool_call` | `{tool, args}` | Tool being invoked |
| `tool_result` | `{tool, result}` | Tool execution result |
| `confirmation_required` | `{tool_call_id, tool, args}` | Waiting for user approval |
| `verification` | `{verdict, claims}` | Claim verification result |
| `system_notice` | `{text}` | System message (time budget, limits) |

#### `GET /api/events`

Persistent SSE connection for multi-tab synchronization. Auth via query token.

```
GET /api/events?token=<NALLY_ACCESS_TOKEN>
```

Broadcasts events like `history_cleared` to all connected tabs.

### Web Frontend

#### `GET /`

Serves `web/index.html` (Jarvis web UI). No auth.

#### `GET /mvp`

Serves the Three.js face avatar frontend from `web/mvp/index.html`. No auth.

#### `GET /web/`

Redirects to `/` with a 302. No auth.

#### `GET /debug`

Debug console HTML page. No auth.

### Session

#### `GET /api/history`

Get conversation history for the current session.

**Response:**
```json
{
  "messages": [
    {"role": "user", "content": "Hello"},
    {"role": "assistant", "content": "Hey!"}
  ]
}
```

#### `POST /api/clear`

Clear conversation history.

#### `POST /api/approve`

Approve or deny a pending tool execution.

**Request:**
```json
{
  "tool_call_id": "tc_run_command_0",
  "approved": true
}
```

#### `POST /api/abort`

Abort the current running session.

#### `POST /api/abort/clear`

Clear the abort flag.

### Status & Info

#### `GET /api/status`

Server status (no auth). Returns provider, active model, tool count, uptime, and framework.

**Response:**
```json
{
  "status": "online",
  "provider": "opencode",
  "model": "hy3-free",
  "tools": 25,
  "uptime": 12345.67,
  "framework": "fastapi",
  "streaming": "websocket+sse"
}
```

#### `GET /api/me`

Current auth status (Bearer auth required).

**Response:**
```json
{
  "authenticated": true,
  "session": "web:default"
}
```

### Tracing

#### `GET /api/traces`

List recent execution traces.

**Query params:** `limit` (default: 50)

#### `GET /api/trace/{run_id}`

Get full nested span tree for a run.

### Permissions & Skills

#### `GET /api/permissions`

Get current permission configuration from `permissions.json`.

#### `GET /api/skills`

List available skills with descriptions and allowed tools.

### MCP Services

#### `GET /api/mcp/services`

List all configured MCP servers with connection status.

#### `POST /api/mcp/connect/{service}`

Initiate OAuth connection for an MCP service.

#### `POST /api/mcp/token/{service}`

Submit a PAT/bot token for token-based MCP services.

**Request:**
```json
{
  "token": "ghp_xxxxxxxxxxxx"
}
```

#### `POST /api/mcp/disconnect/{service}`

Disconnect an MCP service and remove stored tokens.

### OAuth Callbacks

#### `GET /api/oauth/notion/callback`
#### `GET /api/oauth/google/callback`
#### `GET /api/oauth/github/callback`
#### `GET /api/oauth/higgsfield/callback`

OAuth redirect endpoints (no auth — called by external providers).

### Config

#### `POST /api/env/{key}`

Set an environment variable at runtime and persist to `.env`.

### Telegram

#### `POST /telegram/webhook/{token}`

Telegram webhook receiver (token-based auth, no Bearer token).

#### `POST /api/telegram/message`

Message entry point used by the standalone Telegram bot process to forward a user message for processing. **No Bearer auth** — intentionally unauthenticated so the separate bot subprocess can call it. Requests originate from `run_bot_standalone.py`; expose it only on a private/trusted network.

**Request:**
```json
{
  "session_id": "telegram:123",
  "chat_id": 123,
  "text": "hello"
}
```

**Response:**
```json
{
  "response": "Hey!"
}
```

#### `POST /api/telegram/approve`

Approval resolution endpoint used by the standalone bot process to resolve a pending tool approval. **No Bearer auth** — same design as `POST /api/telegram/message`.

**Request:**
```json
{
  "tc_id": "tc_run_command_0",
  "approved": true
}
```

**Response:**
```json
{
  "resolved": true
}
```

### WebSocket

#### `WS /ws/{session_id}`

Bidirectional WebSocket chat. Auth via query token.

```
WS /ws/web:default?token=<NALLY_ACCESS_TOKEN>
```

Supports text messages and voice (browser mic audio).

### Health (No Auth)

These endpoints skip Bearer auth, but they are still subject to the per-IP rate limiter (see [Rate Limiting](#rate-limiting)). Bypass is only at the FastAPI route level — the HTTP middleware rate limiter still applies.

#### `GET /health`

Full health check (DB, Redis, tools). Returns 200 when healthy or 503 when degraded.

#### `GET /health/live`

Kubernetes liveness probe. Returns `{"status": "alive"}`.

#### `GET /health/ready`

Kubernetes readiness probe. Checks DB and Redis connectivity.

## Error Format

All errors follow the typed error structure:

```json
{
  "detail": {
    "code": "tool_not_found",
    "message": "Tool 'foo' does not exist",
    "severity": "error",
    "retryable": false
  }
}
```

**HTTP Status Codes:**

| Code | Meaning |
|------|---------|
| 400 | Bad request (missing/invalid fields) |
| 401 | Unauthorized (missing/invalid token) |
| 404 | Not found |
| 429 | Rate limit exceeded |
| 500 | Internal server error |
| 503 | Service unhealthy |

## Rate Limiting

Token bucket algorithm per IP, applied via HTTP middleware:
- **Rate**: 30 requests/minute (configurable via `RATE_LIMIT_RPM`)
- **Burst**: 60 (configurable via `RATE_LIMIT_BURST`)
- Disabled when `RATE_LIMIT_ENABLED=false`.

The limiter applies to all HTTP requests (including the health endpoints and other no-auth routes) except `/static/*`, `/generated/*`, `/mvp/static/*`, and `/favicon.ico`. This includes the initial request of the persistent SSE endpoint (`/api/events`), since it is an HTTP GET. WebSocket connections (`/ws/{session_id}`) bypass the rate limiter — the HTTP middleware does not apply to WebSockets.
