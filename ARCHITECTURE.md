# Architecture

## System Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (Vanilla JS)                 │
│                    web/index.html                        │
└──────────────────────┬──────────────────────────────────┘
                       │ SSE / HTTP
                       ▼
┌─────────────────────────────────────────────────────────┐
│                 FastAPI Server (web/app.py)              │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────┐  │
│  │ Auth     │  │ Rate     │  │ Request  │  │ CORS   │  │
│  │ Bearer   │  │ Limiter  │  │ ID       │  │        │  │
│  └──────────┘  └──────────┘  └──────────┘  └────────┘  │
└──────────────────────┬──────────────────────────────────┘
                       │
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

### 1. Chat Request (SSE)

```
POST /api/chat
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

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/status` | Server status, provider, model |
| POST | `/api/chat` | Chat with SSE streaming |
| POST | `/api/jarvis` | Chat without streaming |
| GET | `/api/history` | Conversation history |
| POST | `/api/clear` | Clear conversation |
| POST | `/api/approval` | Resolve tool approval |
| GET | `/api/permissions` | Get permission config |
