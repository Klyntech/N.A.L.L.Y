# Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (Vanilla JS)                 │
│                    web/index.html                        │
└──────────────────────┬──────────────────────────────────┘
                       │ SSE / WebSocket / HTTP
                       ▼
┌─────────────────────────────────────────────────────────┐
│                 FastAPI Server (web/app.py)              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  │ Auth     │  │ Rate     │  │ Request  │  │ CORS   │  │
│  │ Bearer   │  │ Limiter  │  │ ID       │  │        │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────┘  │
└──────────────────────┬──────────────────────────────────┘
                       │
         ┌─────────────┼─────────────┐
         ▼             ▼             ▼
   ┌──────────┐  ┌──────────┐  ┌──────────┐
   │ SSE      │  │WebSocket │  │ HTTP     │
   │ Stream   │  │ Bidir.   │  │ REST     │
   └────┬─────┘  └────┬─────┘  └──────────┘
        │              │
        └──────┬───────┘
               ▼
┌─────────────────────────────────────────────────────────┐
│              NallyAgent (agent/core.py)                  │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │ Pattern      │  │ LLM Process  │  │ Context       │  │
│  │ Matcher      │  │ (LangGraph)  │  │ Manager       │  │
│  └──────┬───────┘  └──────┬───────┘  └───────┬───────┘  │
└─────────┼─────────────────┼──────────────────┼──────────┘
          │                 │                  │
          ▼                 ▼                  ▼
┌──────────────┐  ┌──────────────────┐  ┌──────────────┐
│ Local        │  │ LangGraph Graph  │  │ Memory       │
│ Responses    │  │ (ReAct Loop)     │  │ Repository   │
│ (instant)    │  │                  │  │ (SQLite)     │
└──────────────┘  └────────┬─────────┘  └──────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │ LLM      │ │ Tool     │ │ Tool     │
        │ Call     │ │ Filter   │ │ Executor │
        │ (Groq/   │ │          │ │ (parallel)│
        │ OpenCode)│ │          │ │          │
        └──────────┘ └──────────┘ └──────────┘
```

## Request Flow

### 1. Chat Request (SSE or WebSocket)

```
POST /api/chat  (SSE)  —or—  WS /ws/{session_id}  (WebSocket)
    │
    ├─ Auth check (Bearer token)
    ├─ Rate limit check (per-IP token bucket)
    ├─ Generate request ID
    │
    ▼
NallyAgent.process(message)
    │
    ├─ Try pattern matcher (instant local response)
    │   └─ Match found? → Return immediately
    │
    └─ Fall through to LLM
        │
        ├─ Context manager: compact old messages
        ├─ Context manager: inject relevant memories
        ├─ Tool filter: select tools for this query
        │
        ▼
    LangGraph agent loop (ReAct)
        │
        ├─ LLM call (streaming)
        ├─ Parse tool calls
        ├─ Permission gate check
        ├─ Execute tools (parallel)
        ├─ Loop until done or max iterations
        │
        ▼
    Return final response
        │
        ├─ Create episode (if substantive)
        ├─ Save conversation history
        └─ Stream response via SSE
```

## Core Patterns

### Typed Errors (`nally/core/errors.py`)

Every error in the system carries structured data:

```python
class NallyError(Exception):
    code: str  # e.g. "llm_rate_limit"
    message: str  # Human-readable
    severity: Severity  # low/medium/high/critical
    retryable: bool  # Whether caller should retry
    context: dict  # Additional metadata
```

Error hierarchy:
```
NallyError
├── ToolError         (not_found, failed, timeout, blocked, declined)
├── PermissionDenied  (tool denied by permission gate)
├── LLMError          (rate_limit, overloaded, connection_failed, auth_failed)
├── MemoryError       (storage, corruption)
└── ConfigError       (missing_key, invalid_value)
```

### Permission Gate (`nally/tools/permissions.py`)

Declarative tool access control via `nally/config/permissions.json`:

```json
{
  "run_command": {
    "rules": [
      {"match": {"command": "rm -rf *"}, "decision": "deny"},
      {"match": {"command": "npm install*"}, "decision": "ask"},
      {"match": {"command": "*"}, "decision": "allow"}
    ]
  }
}
```

Flow:
1. Tool called → `gate.check(tool_name, args)` → `PermissionDecision`
2. `ALLOW` → execute immediately
3. `ASK` → emit `confirmation_required` event, wait for user response
4. `DENY` → raise `PermissionDenied`, return error to LLM

### Memory Repository (`nally/memory/store.py`)

Thread-safe, connection-per-operation pattern:

```python
class MemoryRepository:
    def remember(self, key, value, category): ...    # Store fact
    def recall(self, key, category, search): ...     # Retrieve facts
    def add_episode(self, topic, what_happened, ...): ...  # Store episode
    def search_episodes(self, topic, search): ...    # Search episodes
    def decay_old_memories(self): ...                # Confidence decay
    def save_messages(self, messages, session_id): ...  # Persist chat
    def load_messages(self, session_id): ...         # Restore chat
```

Key design decisions:
- **Connection-per-operation**: Each method opens/closes its own SQLite connection. Safe for multi-threaded FastAPI.
- **WAL mode**: Write-ahead logging for concurrent reads during writes.
- **Confidence decay**: Memories decay over time, boosted by access.
- **Bulk operations**: `executemany` for batch inserts, single UPDATE for decay.

### Config (`nally/config.py`)

Single source of truth, no import-time side effects:

```python
# Loads .env at import (no side effects beyond that)
PROVIDER = os.getenv("NALLY_PROVIDER", "opencode")


# Lazy directory creation
def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# Runtime personality injection
def get_system_prompt(user_context=None):
    prompt = SYSTEM_PROMPT
    if user_context:
        prompt += f"\n\n{user_context}"
    return prompt
```

### MCP Integration (`nally/mcp/`)

Model Context Protocol — connects NALLY to external services (GitHub, Notion, Gmail, Google Drive, Calendar, Higgsfield, Telegram, Playwright, Context7, Meta).

**Request flow:**
1. `client.py:connect_mcp_servers()` runs at startup
2. Stdio servers: spawn subprocess, fetch tool list, register as `MCPTool` instances
3. HTTP servers: check for stored OAuth tokens → reconnect if found, else await user connection via web UI
4. API key servers: check env var → connect if set, else await user connection
5. Tool execution: `MCPTool.execute()` spawns a fresh connection per call, calls the tool, returns result

**OAuth flow (`oauth.py`):**
- Notion: RFC 9470/8414 discovery → Dynamic Client Registration → PKCE (S256) → token exchange
- Google (Gmail/Drive/Calendar): Manual client credentials → PKCE → shared token across all Google services
- Higgsfield: DCR → PKCE → token exchange
- Tokens encrypted with Fernet (`NALLY_CRED_KEY`), stored in SQLite `mcp_oauth` table
- PKCE state persisted to SQLite to survive server restarts

### Skills System (`nally/skills/`)

Progressive disclosure skill loading — injects specialized instructions into the agent's context.

**Two-level design:**
- **Level 1 (manifest)**: At startup, `get_skill_manifest()` scans `skills/*/SKILL.md`, extracts name + description (~100 tokens/skill), injects into system prompt. Cheap enough for all skills.
- **Level 2 (activation)**: When the agent identifies a matching skill, `activate_skill()` loads the full SKILL.md body into the current context.

**Security:** `validate_skill()` checks for prompt injection patterns (e.g., "ignore previous instructions") and suspicious URLs before loading.

**Hot-reload:** `skill_registry.reload()` rescans the skills directory without restarting the server.

### Database Adapters (`nally/db/`)

Optional backends alongside the default SQLite:

- **`postgres.py`**: PostgreSQL adapter using asyncpg connection pool. Same interface as `MemoryRepository` (remember/recall/forget/episodes/messages). Used when `DATABASE_URL` starts with `postgresql://`. Auto-creates schema on first use.
- **`redis.py`**: Redis cache supporting Layerbase REST API (Upstash-compatible) and self-hosted redis-py. Singleton `get_cache()` returns `None` if `REDIS_URL` not set.

### Telegram Bot (`nally/telegram/bot.py`)

DM + group chat interface via `python-telegram-bot`:

- DM: responds to all messages
- Group chat: only responds to @mentions
- Session IDs: `telegram:{chat_id}` (DM), `telegram:group:{chat_id}` (groups)
- Long messages split at paragraph boundaries (Telegram 4096 char limit)
- Modes: polling (dev) or webhook (production)
- Run: `python main.py --telegram` (web + bot) or `--telegram-only`

### Image Generation (`nally/tools/imagegen.py`)

Vision-guided quality loop against Pollinations API (free, no key required):

1. Content-type router maps prompt to model/quality preset (flux for logos, turbo for photos, etc.)
2. Generate image via Pollinations
3. Score with CLIP model
4. If score < threshold: critique with LLM, refine prompt, regenerate
5. Upscale with PIL if needed

**External hard dependency**: Pollinations API — no fallback. This is the only tool with an external dependency besides the LLM provider itself.

### Thread Safety

All singletons use double-checked locking:

```python
_instance = None
_lock = threading.Lock()


def get_agent():
    global _instance
    if _instance is None:
        with _lock:
            if _instance is None:
                _instance = NallyAgent()
    return _instance
```

## Data Flow

### Conversation Persistence

```
User message → NallyAgent.process()
    │
    ├─ Save user message to self.messages
    ├─ Context manager compacts if needed
    │
    ▼
LangGraph agent loop
    │
    ├─ LLM response → Save assistant message
    ├─ Tool calls → Execute, save tool messages
    │
    ▼
memory_store.save_messages(messages, session_id)
    │
    └─ SQLite: INSERT INTO messages (role, content, session_id, ...)
```

### Memory Injection

```
User: "What's my favorite color?"
    │
    ▼
context_manager.inject_memories(query, messages)
    │
    ├─ memory_store.recall(search="favorite color")
    │   └─ SELECT * FROM memories WHERE value LIKE '%favorite color%'
    │
    ├─ Inject as system message:
    │   "[Relevant memories]\n- favorite_color: blue"
    │
    ▼
LLM sees injected context → Responds with remembered fact
```

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | No | Serve web UI (index.html) |
| GET | `/web/` | No | Redirect to `/` |
| GET | `/debug` | No | Debug console page |
| GET | `/api/status` | No | Server status, provider, model, tool count |
| POST | `/api/chat` | Yes (Bearer) | Chat with SSE streaming |
| GET | `/api/events` | Yes (query param) | Persistent SSE for multi-tab sync |
| GET | `/api/history` | Yes | Conversation history |
| POST | `/api/clear` | Yes | Clear conversation |
| POST | `/api/approve` | Yes | Resolve tool approval |
| POST | `/api/abort` | Yes | Abort running session |
| POST | `/api/abort/clear` | Yes | Clear abort flag |
| GET | `/api/permissions` | Yes | Get permission config |
| GET | `/api/skills` | Yes | List available skills |
| GET | `/api/mcp/services` | Yes | List MCP services + connection status |
| POST | `/api/mcp/connect/{service}` | Yes | Initiate MCP connection (OAuth/auth) |
| POST | `/api/mcp/token/{service}` | Yes | Submit PAT/bot token for MCP service |
| POST | `/api/mcp/disconnect/{service}` | Yes | Disconnect MCP service (remove tokens) |
| GET | `/api/oauth/notion/callback` | No | Notion OAuth callback (external redirect) |
| GET | `/api/oauth/google/callback` | No | Google OAuth callback (external redirect) |
| GET | `/api/oauth/higgsfield/callback` | No | Higgsfield OAuth callback (external redirect) |
| POST | `/api/env/{key}` | Yes | Set env var at runtime + persist to .env |
| GET | `/health` | No | Full health check (DB, Redis, tools) |
| GET | `/health/live` | No | Kubernetes liveness probe |
| GET | `/health/ready` | No | Kubernetes readiness probe |
| WS | `/ws/{session_id}` | Yes (query param) | WebSocket bidirectional chat |

**Auth note**: Health endpoints (`/health`, `/health/live`, `/health/ready`) deliberately skip Bearer token auth — they exist for infrastructure probes (Docker, Kubernetes, load balancers) and expose no sensitive data. OAuth callback endpoints also skip auth because they're called by external providers redirecting back, not by the user directly.
