# API Reference

Nally exposes a REST API with SSE streaming and WebSocket support. All endpoints except health and OAuth callbacks require Bearer token auth.

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

data: {"type": "stream_done"}
```

**SSE Event Types:**

| Event | Payload | Description |
|-------|---------|-------------|
| `run_id` | `{run_id}` | Unique ID for this execution trace |
| `stream_chunk` | `{text}` | Partial text from LLM |
| `stream_done` | `{}` | Response complete |
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

Server status (no auth).

**Response:**
```json
{
  "status": "ok",
  "provider": "opencode",
  "model": "hy3-free",
  "tools": 25,
  "mcp_servers": 5
}
```

#### `GET `

Current auth status.

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
#### `GET `

OAuth redirect endpoints (no auth — called by external providers).

### Config

#### `POST /api/env/{key}`

Set an environment variable at runtime and persist to `.env`.

### Telegram

#### `POST /telegram/webhook/{token}`

Telegram webhook receiver (token-based auth, no Bearer token).

### WebSocket

#### `WS /ws/{session_id}`

Bidirectional WebSocket chat. Auth via query token.

```
WS /ws/web:default?token=<NALLY_ACCESS_TOKEN>
```

Supports text messages and voice (browser mic audio).

### Health (No Auth)

#### `GET /health`

Full health check (DB, Redis, tools). Returns 200 or 503.

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

Token bucket algorithm per IP:
- **Rate**: 30 requests/minute (configurable via `RATE_LIMIT_RPM`)
- **Burst**: 60 (configurable via `RATE_LIMIT_BURST`)
