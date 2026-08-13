# Memory System

Nally remembers facts, episodes, and patterns across conversations. The memory system is connection-per-operation (safe for multi-threaded FastAPI) and persists to SQLite by default.

## Memory Types

### Facts

Key-value pairs with confidence scoring:

```python
memory_store.remember(
    key="favorite_color",
    value="blue",
    category="preferences"
)
```

- **Confidence**: Starts at 0.5, decays over time, boosted by access
- **Decay**: Tiered — 1.0 (fresh) → 0.3 (old)
- **Boost**: +0.1 per access, capped at 1.0

### Episodes

Narrative records of what happened:

```python
memory_store.add_episode(
    topic="deployed v2.0",
    what_happened="Successfully deployed to production via Docker",
    outcome="Live on port 5000",
    tags=["deploy", "docker"]
)
```

### Conversation Summaries

Auto-generated summaries of past conversations:

```python
summaries = memory_store.get_conversation_summaries_text()
```

Created automatically every 20 messages or when history is cleared.

### Semantic Patterns

Recurring themes/structures extracted by the background reflector:

```python
memory_store.add_semantic(
    pattern="user prefers concise answers",
    confidence=0.8
)
```

## How Memory Works

### Injection into Conversations

When you ask a question, Nally:

1. Searches memories matching your query
2. Injects relevant facts as a system message: `"[Relevant memories]\n- favorite_color: blue"`
3. LLM sees the context and responds with remembered information

### Auto-Creation

Nally automatically creates memories from substantive conversations:
- Facts extracted from user statements
- Episodes created for significant events
- Summaries generated every 20 messages

### Manual Management

Via tools (Nally can use these proactively):
- `remember(key, value, category)` — Store a fact
- `recall(search, category)` — Search memories
- `forget(key)` — Delete a fact

## Confidence Decay

Memories decay over time unless accessed:

| Age | Confidence Multiplier |
|-----|----------------------|
| 0 days | 1.0 |
| 7 days | 0.8 |
| 30 days | 0.6 |
| 90 days | 0.4 |
| 365+ days | 0.3 |

Accessing a memory (via `recall`) boosts its confidence by +0.1, up to the maximum of 1.0.

Run decay manually:
```python
memory_store.decay_old_memories()
```

## Background Reflector

An hourly daemon thread that reflects on recent conversations:

- Extracts **summaries** (what was discussed)
- Extracts **episodes** (what happened, outcome)
- Extracts **semantic patterns** (recurring themes)

Powered by LLM — uses the same provider as the main agent.

## Database Schema

| Table | Contents |
|-------|----------|
| `memories` | Key-value facts with confidence |
| `episodes` | Narrative episode records |
| `conversations` | Conversation summaries |
| `semantic` | Semantic patterns |
| `conversation_messages` | Raw chat history per session |
| `spans` | Execution trace spans |

## Configuration

- **SQLite** (default): `DATABASE_URL=data/nally.db`
- **PostgreSQL**: Set `DATABASE_URL=postgresql://...` (note: `semantic` and `spans` tables are SQLite-only)
- **WAL mode**: Enabled by default for concurrent read/write

## Session Isolation

- Memories are **global** — shared across all sessions
- Conversation history is **per-session** — identified by `session_id`
- Session IDs: `web:default`, `telegram:123`, `telegram:group:456`

## User Profile

Nally maintains a user profile with recognized keys:

- `name`, `location`, `occupation`, `goals`
- `interests`, `projects`, `preferences`
- `communication_style`, `work_style`

Profile is stored in the `memories` table under the `profile` category and auto-injected into the system prompt as `{{USER_CONTEXT}}`.
