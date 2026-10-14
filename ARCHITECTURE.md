# Architecture

## System Overview

```
User
 │
 ▼
FastAPI (auth, rate limits, request handling)
 │
 ▼
NallyAgent
 ├─ Input guardrails
 ├─ Context + relevant memory
 └─ Registered tool schemas
      │
      ▼
   LLM-driven ReAct loop
      ├─ Model answers, or requests a tool
      ├─ Permission gate checks tool call
      ├─ Runtime executes and returns result
      └─ Model continues until done or bounded
 │
 ▼
Response stream + conversation persistence
```┌─────────────────────────────────────────────────────────┐
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
    ├─ Input guardrails
    ├─ Context manager: compact history and inject relevant memory
    ├─ Read schemas from the registered tool registry
    │
    ▼
    LangGraph agent loop (ReAct)
        ├─ LLM chooses a direct answer or tool call
        ├─ Runtime validates permissions and executes the call
        ├─ Tool result or structured error returns to the LLM
        ├─ Continue until the model finishes or a hard limit is reached
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
├── ConfigError       (missing_key, invalid_value)
└── PlanError         (generation_failed, max_revisions_exceeded, step_unrecoverable)
```

### Permission Gate (`nally/tools/permissions.py`)

Declarative tool access control via `nally/config/permissions.json`:

```json
{
  "run_command": {
    "rules": [
      {"match": {"command": "rm -rf *"}, "decision": "ask"},
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

MCP and OAuth code remains in the web layer for account-linking and service-management flows. The core tool loader does not dynamically register external MCP tools into the model-callable registry. The LLM receives only the schemas of tools explicitly registered by the core tool loader. Treat the older dynamic-MCP execution path as inactive unless it is deliberately reintroduced and tested.

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

### Execution Tracing (`nally/core/tracing.py`)

Nested span-based tracing with parent-child relationships, run IDs, and thread-local span stacks:

```python
class Tracer:
    def start_span(self, name, input, parent_span_id=None, run_id=None) -> Span
    def end_span(self, span_id, output=None, error=None) -> Optional[Span]
    def get_run_tree(self, run_id) -> Optional[dict]  # Build tree from flat spans
    def list_runs(self, limit=50) -> List[dict]
```

- **Span**: `span_id`, `parent_span_id`, `run_id`, `name`, `status`, `input`, `output`, `error`, `started_at`, `ended_at`
- **Thread-local span stack**: Auto-detects parent from current thread context
- **Persistence**: Spans saved to SQLite `spans` table via `MemoryRepository.save_span()`
- **API**: `GET /api/traces` (list runs), `GET /api/trace/{run_id}` (run tree detail)

### Tool Receipts (`nally/tools/receipts.py`)

Every tool execution generates an HMAC-signed receipt stored in JSONL:

```python
class ReceiptStore:
    def record(self, tool_call_id, tool, args, result, success, duration_ms) -> Receipt
    def get(self, tool_call_id) -> Optional[Receipt]
    def verify(self, receipt) -> bool  # Verify HMAC integrity
    def format_for_context(self, receipts) -> str  # For claim verifier
```

- **Tamper-evident**: SHA-256 hash + HMAC-SHA256 signature per receipt
- **Auto-rotation**: JSONL files rotate at 10MB, keeps 5 rotated files
- **In-memory index**: By `tool_call_id` for O(1) lookup
- **Used by**: Claim verifier to cross-check LLM claims

### Claim Verifier (`nally/agent/verifier.py`)

Post-response verification that cross-checks LLM claims against tool receipts — detects hallucinations without LLM in the hot path:

```python
class ClaimVerifier:
    def verify(self, llm_response, receipts) -> VerificationResult
    # Verdicts: BACKED, UNSUPPORTED, CONTRADICTED, PARTIAL
```

- **Deterministic**: Regex-based claim extraction, no LLM in verification hot path
- **Detects**: tool_bypass (claimed action not in receipts), false_success, false_failure
- **Emits**: `verification` event with verdict details

### Active Agent Loop

Nally uses one direct ReAct graph:

`LLM → registered tools → tool results → LLM`

Every user request goes through the same model-driven execution path after input guardrails. There is no local pattern-matcher response bypass, keyword-based tool filter, intent-classification Harness, scratchpad pipeline, or Plan-and-Execute graph in the active runtime.

The model receives the schemas for the tools currently in the runtime registry and decides which tools are relevant. The registry starts with the default core tools; explicitly connected MCP services may add schemas. Tool execution still passes through the permission gate, retry policy, execution receipts, error handling, abort checks, iteration limits, and wall-clock limits. The graph ends when the model stops requesting tools or a safety limit is reached.

The system prompt describes behavior and truthfulness, but does not decide tool availability. The runtime registry and the schemas supplied on each request are the source of truth for the tools the model can call.

### Background Reflector (`nally/memory/reflector.py`)

Hourly LLM-powered reflection engine running in a daemon thread:

```python
class Reflector:
    def daily_reflection(self) -> None       # Hourly batch reflection
    def reflect_on_conversation(self) -> None # Post-conversation reflection
    # Extracts: ConversationSummary, Episode, SemanticPattern
```

- **Extracts**: Summaries, episodes, semantic patterns from recent conversations
- **Semantic patterns**: Recurring themes/structures stored in `semantic` table with confidence scoring
- **Singleton**: `reflector = Reflector()` — started during FastAPI lifespan

### Event Bus (`nally/events/bus.py`)

Pub/sub event bus for decoupled communication:

- **Agent notifications**: Streaming events forwarded to WebSocket/SSE subscribers
- Used to forward agent and application events to WebSocket/SSE subscribers.

### Database

SQLite is the only data store (`data/nally.db` for chat/state, `data/nally_memory.db` for memory). There is no `nally/db/` module — PostgreSQL/Redis exist only as reachability health probes:

- `nally/web/health.py` checks `DATABASE_URL` starting with `postgresql://`/`postgres://` via `asyncpg`, and `REDIS_URL` via Layerbase/Upstash REST or `redis.asyncio`, when configured
- `nally/core/validator.py` warns on invalid Postgres/Redis URL formats and missing `asyncpg` at startup
- No adapter implements `MemoryRepository` against Postgres/Redis; the memory layer is SQLite-only

### Telegram Bot (`nally/telegram/bot.py`)

DM + group chat interface via `python-telegram-bot`:

- DM: responds to all messages
- Group chat: only responds to @mentions
- Session IDs: `telegram:{chat_id}` (DM), `telegram:group:{chat_id}` (groups)
- Long messages split at paragraph boundaries (Telegram 4096 char limit)
- Modes: polling (dev) or webhook (production)
- Run: `python main.py --telegram-only` (bot only, no web server)

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
| GET | `/api/me` | Yes | Current user/session info |
| GET | `/api/traces` | Yes | List recent execution trace runs |
| GET | `/api/trace/{run_id}` | Yes | Get full trace tree for a run |
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
| POST | `/telegram/webhook/{token}` | No | Telegram webhook receiver (token-based auth) |
| GET | `/health` | No | Full health check (DB, Redis, tools) |
| GET | `/health/live` | No | Kubernetes liveness probe |
| GET | `/health/ready` | No | Kubernetes readiness probe |
| WS | `/ws/{session_id}` | Yes (query param) | WebSocket bidirectional chat |

**Auth note**: Health endpoints (`/health`, `/health/live`, `/health/ready`) deliberately skip Bearer token auth — they exist for infrastructure probes (Docker, Kubernetes, load balancers) and expose no sensitive data. OAuth callback endpoints also skip auth because they're called by external providers redirecting back, not by the user directly.
