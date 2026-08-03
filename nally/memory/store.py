"""Memory Repository — SQLite-backed persistence with connection-per-operation.

Thread-safe: every operation creates its own connection and transaction.
No shared state between threads. WAL mode for concurrent reads.

Supports SQLite (default) and Turso/LibSQL via DATABASE_URL.
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import DATA_DIR
from .confidence import boost_confidence, days_since, decay_confidence, initial_confidence

# ── Profile Keys ───────────────────────────────────────────

RECOGNIZED_PROFILE_KEYS = {
    "name",
    "preferred_name",
    "aliases",
    "age",
    "location",
    "occupation",
    "education",
    "communication_style",
    "timezone",
    "languages_spoken",
    "languages_to_learn",
    "coding_level",
    "coding_languages",
    "projects",
    "goals",
    "interests",
    "favorite_apps",
    "work_hours",
    "notes",
}


# ── Schema ────────────────────────────────────────────────

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    key TEXT NOT NULL,
    value TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    confidence REAL DEFAULT 0.5,
    mention_count INTEGER DEFAULT 1,
    created TEXT NOT NULL,
    last_confirmed TEXT NOT NULL,
    deleted INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key);
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_deleted ON memories(deleted);

CREATE TABLE IF NOT EXISTS episodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    topic TEXT NOT NULL,
    what_happened TEXT NOT NULL,
    outcome TEXT DEFAULT '',
    solution TEXT DEFAULT '',
    tags TEXT DEFAULT '[]',
    created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_episodes_date ON episodes(date);
CREATE INDEX IF NOT EXISTS idx_episodes_topic ON episodes(topic);

CREATE TABLE IF NOT EXISTS conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    summary TEXT NOT NULL,
    topics TEXT DEFAULT '[]',
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    message_count INTEGER DEFAULT 0,
    created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_convos_start ON conversations(start_date);

CREATE TABLE IF NOT EXISTS semantic (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL UNIQUE,
    confidence REAL DEFAULT 0.5,
    evidence_count INTEGER DEFAULT 1,
    last_seen TEXT NOT NULL,
    created TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_semantic_pattern ON semantic(pattern);

CREATE TABLE IF NOT EXISTS conversation_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tool_calls TEXT DEFAULT NULL,
    tool_call_id TEXT DEFAULT NULL,
    timestamp TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_conv_msg_session ON conversation_messages(session_id);
"""


class MemoryRepository:
    """SQLite-backed memory with connection-per-operation.

    Thread-safe, transactional, no shared connections.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or DATA_DIR / "nally_memory.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._schema_initialized = False
        self._working: Dict[str, Any] = {}

    def _create_connection(self) -> sqlite3.Connection:
        """Create a fresh SQLite connection. Caller owns it."""
        conn = sqlite3.connect(str(self._db_path), timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    @contextmanager
    def _connection(self):
        """Context manager that yields a connection, commits on success, rolls back on error."""
        conn = self._create_connection()
        try:
            self._ensure_schema(conn)
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _ensure_schema(self, conn: sqlite3.Connection):
        """Create tables if they don't exist. Runs once per connection."""
        if not self._schema_initialized:
            conn.executescript(_SCHEMA)
            self._schema_initialized = True

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat()

    # ── Long-term Memory ──────────────────────────────────────

    def remember(self, key: str, value: str, category: str = "general") -> str:
        """Store a fact. Boosts confidence if key already exists."""
        # Warn when storing profile facts with unrecognized keys
        if category == "profile" and key not in RECOGNIZED_PROFILE_KEYS:
            import logging

            logging.getLogger("nally.memory").warning(
                f"Profile fact '{key}' is not a recognized profile key. "
                f"Recognized keys: {', '.join(sorted(RECOGNIZED_PROFILE_KEYS))}"
            )
        now = self._now()
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT id, confidence, mention_count FROM memories WHERE key = ? AND deleted = 0",
                (key,),
            ).fetchone()

            if existing:
                new_confidence = boost_confidence(existing["confidence"], 0.1)
                new_count = existing["mention_count"] + 1
                conn.execute(
                    "UPDATE memories SET value = ?, category = ?, confidence = ?, mention_count = ?, last_confirmed = ? WHERE id = ?",
                    (value, category, new_confidence, new_count, now, existing["id"]),
                )
                return f"Updated: {key} = {value} (confidence: {new_confidence:.1f}, mentions: {new_count})"
            else:
                conn.execute(
                    "INSERT INTO memories (key, value, category, confidence, mention_count, created, last_confirmed) VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (key, value, category, initial_confidence(), 1, now, now),
                )
                return f"Remembered: {key} = {value}"

    def recall(
        self,
        key: Optional[str] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 20,
    ) -> Any:
        """Recall memories with confidence filtering."""
        with self._connection() as conn:
            if key:
                row = conn.execute("SELECT * FROM memories WHERE key = ? AND deleted = 0", (key,)).fetchone()
                if row:
                    # Boost confidence on recall
                    conn.execute(
                        "UPDATE memories SET confidence = MIN(1.0, confidence + 0.05), last_confirmed = ? WHERE id = ?",
                        (self._now(), row["id"]),
                    )
                    return row["value"]
                return None

            if category:
                rows = conn.execute(
                    "SELECT * FROM memories WHERE category = ? AND deleted = 0 AND confidence >= ? ORDER BY confidence DESC, last_confirmed DESC LIMIT ?",
                    (category, min_confidence, limit),
                ).fetchall()
                return {row["key"]: row["value"] for row in rows}

            if search:
                # SQL LIKE instead of Python filtering
                like_pattern = f"%{search}%"
                rows = conn.execute(
                    "SELECT * FROM memories WHERE deleted = 0 AND confidence >= ? AND (key LIKE ? OR value LIKE ? OR category LIKE ?) ORDER BY confidence DESC LIMIT ?",
                    (min_confidence, like_pattern, like_pattern, like_pattern, limit),
                ).fetchall()
                return {row["key"]: row["value"] for row in rows}

            # Return all high-confidence memories
            rows = conn.execute(
                "SELECT * FROM memories WHERE deleted = 0 AND confidence >= ? ORDER BY confidence DESC, last_confirmed DESC LIMIT ?",
                (min_confidence, limit),
            ).fetchall()
            return {row["key"]: row["value"] for row in rows}

    def forget(self, key: str) -> str:
        """Soft delete a memory."""
        with self._connection() as conn:
            row = conn.execute("SELECT id FROM memories WHERE key = ? AND deleted = 0", (key,)).fetchone()
            if row:
                conn.execute("UPDATE memories SET deleted = 1 WHERE id = ?", (row["id"],))
                return f"Forgot: {key}"
            return f"Don't remember: {key}"

    def get_memory_stats(self) -> Dict[str, Any]:
        """Get statistics about stored memories."""
        with self._connection() as conn:
            # Single query with aggregations instead of 4 separate queries
            row = conn.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN confidence >= 0.8 THEN 1 ELSE 0 END) as high_conf,
                    SUM(CASE WHEN confidence < 0.5 THEN 1 ELSE 0 END) as low_conf
                FROM memories WHERE deleted = 0
            """).fetchone()

            by_cat = conn.execute(
                "SELECT category, COUNT(*) as c FROM memories WHERE deleted = 0 GROUP BY category"
            ).fetchall()

            return {
                "total_memories": row["total"],
                "by_category": {r["category"]: r["c"] for r in by_cat},
                "high_confidence": row["high_conf"],
                "low_confidence": row["low_conf"],
            }

    def decay_old_memories(self):
        """Decay confidence for memories not confirmed in a while.

        Uses a single bulk UPDATE instead of N individual updates.
        """
        with self._connection() as conn:
            rows = conn.execute("SELECT id, last_confirmed FROM memories WHERE deleted = 0").fetchall()

            updates = []
            for row in rows:
                days = days_since(row["last_confirmed"])
                factor = decay_confidence(days)
                if factor < 1.0:
                    updates.append((factor, row["id"]))

            if updates:
                conn.executemany(
                    "UPDATE memories SET confidence = confidence * ? WHERE id = ?",
                    updates,
                )

    # ── Episodic Memory ───────────────────────────────────────

    def add_episode(
        self,
        topic: str,
        what_happened: str,
        outcome: str = "",
        solution: str = "",
        tags: Optional[List[str]] = None,
    ) -> str:
        """Record an experience."""
        now = self._now()
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO episodes (date, topic, what_happened, outcome, solution, tags, created) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (now, topic, what_happened, outcome, solution, json.dumps(tags or []), now),
            )
        return f"Episode recorded: {topic}"

    def search_episodes(
        self,
        topic: Optional[str] = None,
        search: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict]:
        """Search episodic memory."""
        with self._connection() as conn:
            if topic:
                rows = conn.execute(
                    "SELECT * FROM episodes WHERE topic LIKE ? ORDER BY date DESC LIMIT ?",
                    (f"%{topic}%", limit),
                ).fetchall()
            elif search:
                like = f"%{search}%"
                rows = conn.execute(
                    "SELECT * FROM episodes WHERE what_happened LIKE ? OR topic LIKE ? OR solution LIKE ? ORDER BY date DESC LIMIT ?",
                    (like, like, like, limit),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM episodes ORDER BY date DESC LIMIT ?", (limit,)).fetchall()

            return [dict(row) for row in rows]

    # ── Conversation Memory ───────────────────────────────────

    def save_conversation(
        self,
        summary: str,
        topics: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        message_count: int = 0,
    ) -> str:
        """Save a conversation summary."""
        now = self._now()
        with self._connection() as conn:
            conn.execute(
                "INSERT INTO conversations (summary, topics, start_date, end_date, message_count, created) VALUES (?, ?, ?, ?, ?, ?)",
                (summary, json.dumps(topics or []), start_date or now, now, message_count, now),
            )
        return "Conversation saved"

    def get_recent_conversations(self, limit: int = 5) -> List[Dict]:
        """Get recent conversation summaries for context injection."""
        with self._connection() as conn:
            rows = conn.execute("SELECT * FROM conversations ORDER BY end_date DESC LIMIT ?", (limit,)).fetchall()
            return [dict(row) for row in rows]

    def get_conversation_summaries_text(self, limit: int = 3) -> str:
        """Get formatted conversation summaries for system prompt injection."""
        convos = self.get_recent_conversations(limit)
        if not convos:
            return ""
        lines = ["Recent conversation history:"]
        for c in convos:
            date = c["end_date"][:10] if c["end_date"] else "unknown"
            topics = json.loads(c["topics"]) if c["topics"] else []
            topic_str = ", ".join(topics[:3]) if topics else "general"
            lines.append(f"- {date} [{topic_str}]: {c['summary'][:150]}")
        return "\n".join(lines)

    # ── Semantic Memory ───────────────────────────────────────

    def add_semantic(self, pattern: str, confidence: float = 0.5) -> str:
        """Add or update a semantic pattern."""
        now = self._now()
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT id, confidence, evidence_count FROM semantic WHERE pattern = ?",
                (pattern,),
            ).fetchone()

            if existing:
                new_conf = boost_confidence(existing["confidence"], 0.15)
                new_count = existing["evidence_count"] + 1
                conn.execute(
                    "UPDATE semantic SET confidence = ?, evidence_count = ?, last_seen = ? WHERE id = ?",
                    (new_conf, new_count, now, existing["id"]),
                )
                return f"Pattern reinforced: {pattern} (confidence: {new_conf:.1f})"
            else:
                conn.execute(
                    "INSERT INTO semantic (pattern, confidence, evidence_count, last_seen, created) VALUES (?, ?, ?, ?, ?)",
                    (pattern, confidence, 1, now, now),
                )
                return f"Pattern learned: {pattern}"

    def recall_semantic(self, search: Optional[str] = None, min_confidence: float = 0.5) -> List[Dict]:
        """Recall semantic patterns."""
        with self._connection() as conn:
            if search:
                rows = conn.execute(
                    "SELECT * FROM semantic WHERE pattern LIKE ? AND confidence >= ? ORDER BY confidence DESC",
                    (f"%{search}%", min_confidence),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM semantic WHERE confidence >= ? ORDER BY confidence DESC",
                    (min_confidence,),
                ).fetchall()
            return [dict(row) for row in rows]

    # ── Working Memory (in-process, not persisted) ────────────

    def set_working(self, key: str, value: Any):
        self._working[key] = value

    def get_working(self, key: Optional[str] = None) -> Any:
        if key:
            return self._working.get(key)
        return dict(self._working)

    def clear_working(self):
        self._working.clear()

    # ── Profile Integration ───────────────────────────────────

    def get_user_facts(self) -> str:
        """Get formatted user facts for system prompt injection."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT key, value, confidence FROM memories WHERE deleted = 0 AND confidence >= 0.2 ORDER BY confidence DESC LIMIT 30"
            ).fetchall()
            if not rows:
                return "No user facts stored yet."
            lines = []
            for row in rows:
                marker = "*" if row["confidence"] >= 0.8 else ""
                lines.append(f"- {row['key']}: {row['value']}{marker}")
            return "\n".join(lines)

    def reset_stale_facts(self, min_confidence: float = 0.35, target: float = 0.5):
        """Boost decayed profile facts back to visible threshold."""
        with self._connection() as conn:
            conn.execute(
                "UPDATE memories SET confidence = ? WHERE confidence < ? AND deleted = 0",
                (target, min_confidence),
            )

    # ── Conversation History Persistence ──────────────────────

    def save_messages(self, messages: List[Dict[str, Any]], session_id: str = "default") -> str:
        """Save full conversation messages to database."""
        now = self._now()
        with self._connection() as conn:
            # Clear old messages for this session
            conn.execute("DELETE FROM conversation_messages WHERE session_id = ?", (session_id,))

            # Bulk insert with executemany
            rows = []
            for msg in messages:
                rows.append(
                    (
                        session_id,
                        msg.get("role", "user"),
                        msg.get("content", ""),
                        json.dumps(msg.get("tool_calls")) if msg.get("tool_calls") else None,
                        msg.get("tool_call_id"),
                        now,
                    )
                )
            conn.executemany(
                "INSERT INTO conversation_messages (session_id, role, content, tool_calls, tool_call_id, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
        return f"Saved {len(messages)} messages"

    def load_messages(self, session_id: str = "default") -> List[Dict[str, Any]]:
        """Load conversation messages from database (limited to recent messages)."""
        from ..config import MAX_CONVERSATION_HISTORY

        with self._connection() as conn:
            rows = conn.execute(
                "SELECT role, content, tool_calls, tool_call_id FROM conversation_messages "
                "WHERE session_id = ? ORDER BY id DESC LIMIT ?",
                (session_id, MAX_CONVERSATION_HISTORY),
            ).fetchall()

            messages = []
            for row in reversed(rows):
                msg = {"role": row["role"], "content": row["content"]}
                tc = row["tool_calls"]
                if tc and tc not in ("None", "null", ""):
                    try:
                        msg["tool_calls"] = json.loads(tc)
                    except (json.JSONDecodeError, TypeError):
                        pass
                tcid = row["tool_call_id"]
                if tcid and tcid not in ("None", "null", ""):
                    msg["tool_call_id"] = tcid
                messages.append(msg)
            return messages

    def get_last_session_id(self) -> Optional[str]:
        """Get the most recent session ID."""
        with self._connection() as conn:
            try:
                row = conn.execute("SELECT session_id FROM conversation_messages ORDER BY id DESC LIMIT 1").fetchone()
                return row["session_id"] if row else None
            except sqlite3.OperationalError:
                return None


# ── Profile Migration ─────────────────────────────────────


def migrate_profile(store: "MemoryRepository"):
    """One-time migration: read data/user_profile.json into memory store.

    Writes each field with category="profile", then renames the file
    to user_profile.json.migrated so it's not re-imported.
    """
    profile_path = DATA_DIR / "user_profile.json"
    if not profile_path.exists():
        return

    try:
        data = json.loads(profile_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return

    if not isinstance(data, dict):
        return

    count = 0
    for key, value in data.items():
        # Serialize complex types (lists, dicts) to JSON strings
        if isinstance(value, (list, dict)):
            value = json.dumps(value, default=str)
        else:
            value = str(value)
        store.remember(key, value, category="profile")
        count += 1

    # Rename to prevent re-import
    migrated_path = profile_path.with_suffix(".json.migrated")
    try:
        profile_path.rename(migrated_path)
    except OSError:
        pass


# ── Tool Definitions (OpenAI function schemas) ─────────────

MEMORY_TOOL_SCHEMAS = [
    {
        "type": "function",
        "function": {
            "name": "remember",
            "description": "Store a fact or record an episode. Use type=fact for preferences, facts, people. Use type=episode for experiences, debugging sessions, lessons learned.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "A short label (e.g. 'favorite_color', 'deploy_fix')",
                    },
                    "value": {
                        "type": "string",
                        "description": "The information to remember (for type=fact)",
                    },
                    "category": {
                        "type": "string",
                        "description": "Category for organization",
                        "enum": ["general", "preference", "task", "people", "project", "goal", "habit", "fact"],
                    },
                    "type": {
                        "type": "string",
                        "enum": ["fact", "episode"],
                        "description": "fact = store a preference/fact, episode = record an experience",
                    },
                    "topic": {
                        "type": "string",
                        "description": "Short topic label for episodes (e.g. 'Render deployment fix')",
                    },
                    "what_happened": {
                        "type": "string",
                        "description": "What happened (for type=episode)",
                    },
                    "outcome": {
                        "type": "string",
                        "description": "What was the result (for type=episode)",
                    },
                    "solution": {
                        "type": "string",
                        "description": "How it was resolved (for type=episode)",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for search (for type=episode)",
                    },
                },
                "required": ["key", "value"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "Retrieve facts or episodes from memory. Use type=fact for preferences/facts, type=episode for past experiences.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "The exact key to look up",
                    },
                    "category": {
                        "type": "string",
                        "description": "Filter by category",
                    },
                    "search": {
                        "type": "string",
                        "description": "Search across all memories by keyword",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["fact", "episode"],
                        "description": "fact = retrieve preferences/facts, episode = retrieve past experiences",
                    },
                    "topic": {
                        "type": "string",
                        "description": "Filter episodes by topic",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget",
            "description": "Remove something from memory",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "The key to forget",
                    },
                },
                "required": ["key"],
            },
        },
    },
]


# ── Backend Factory ────────────────────────────────────────


def create_memory_store():
    """Create the appropriate memory store based on config.

    Returns PostgreSQLDatabase if DATABASE_URL starts with postgresql://,
    otherwise returns SQLite-backed MemoryRepository.
    """
    import os

    database_url = os.getenv("DATABASE_URL", "")

    if database_url and database_url.startswith(("postgresql://", "postgres://")):
        try:
            from ..db.postgres import PostgreSQLDatabase

            return PostgreSQLDatabase(database_url)
        except Exception as e:
            import logging

            logging.getLogger("nally.memory").warning(f"PostgreSQL backend failed ({e}), falling back to SQLite")

    return MemoryRepository()
