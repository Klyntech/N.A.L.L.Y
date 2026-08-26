"""Memory Repository — SQLite-backed persistence with connection-per-operation.

Thread-safe: every operation creates its own connection and transaction.
No shared state between threads. WAL mode for concurrent reads.

Supports SQLite (default) and Turso/LibSQL via TURSO_URL.
"""

import json
import sqlite3
import time as _time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import DATA_DIR, TURSO_URL, TURSO_TOKEN
from .confidence import boost_confidence, days_since, decay_confidence

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
    deleted INTEGER DEFAULT 0,
    expires_at TEXT DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_key ON memories(key);
CREATE INDEX IF NOT EXISTS idx_memories_category ON memories(category);
CREATE INDEX IF NOT EXISTS idx_memories_deleted ON memories(deleted);
CREATE INDEX IF NOT EXISTS idx_memories_expires ON memories(expires_at);

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

CREATE TABLE IF NOT EXISTS spans (
    span_id TEXT PRIMARY KEY,
    parent_span_id TEXT,
    run_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT DEFAULT 'running',
    input_json TEXT DEFAULT '{}',
    output_json TEXT,
    error TEXT,
    started_at REAL NOT NULL,
    ended_at REAL
);
CREATE INDEX IF NOT EXISTS idx_spans_run_id ON spans(run_id);
CREATE INDEX IF NOT EXISTS idx_spans_started ON spans(started_at);

CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(key, value, category, content='memories', content_rowid='id');
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, key, value, category) VALUES (new.id, new.key, new.value, new.category);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, key, value, category) VALUES('delete', old.id, old.key, old.value, old.category);
END;
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, key, value, category) VALUES('delete', old.id, old.key, old.value, old.category);
    INSERT INTO memories_fts(rowid, key, value, category) VALUES (new.id, new.key, new.value, new.category);
END;
"""


def _backfill_expires_at_column(conn: sqlite3.Connection):
    """Add expires_at column to memories table if missing."""
    try:
        cols = [row[1] for row in conn.execute("PRAGMA table_info(memories)").fetchall()]
        if "expires_at" not in cols:
            conn.execute("ALTER TABLE memories ADD COLUMN expires_at TEXT DEFAULT NULL")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_expires ON memories(expires_at)")
    except Exception:
        pass


class _LibSQLRow:
    """Dict-like wrapper for libsql tuple rows — enables row["column_name"] access."""
    __slots__ = ("_data", "_keys")
    def __init__(self, row_tuple, description):
        self._data = row_tuple
        self._keys = {desc[0]: i for i, desc in enumerate(description)}
    def __getitem__(self, key):
        if isinstance(key, str):
            return self._data[self._keys[key]]
        return self._data[key]
    def get(self, key, default=None):
        try:
            return self[key]
        except (KeyError, IndexError):
            return default
    def __iter__(self):
        return iter(self._data)
    def __len__(self):
        return len(self._data)


class _LibSQLCursorWrapper:
    """Wraps libsql cursor to return _LibSQLRow objects from fetchone/fetchall."""
    __slots__ = ("_cursor",)
    def __init__(self, cursor):
        self._cursor = cursor
    def fetchone(self):
        row = self._cursor.fetchone()
        if row is None:
            return None
        return _LibSQLRow(row, self._cursor.description)
    def fetchall(self):
        desc = self._cursor.description
        return [_LibSQLRow(r, desc) for r in self._cursor.fetchall()]
    def __iter__(self):
        desc = self._cursor.description
        for r in self._cursor:
            yield _LibSQLRow(r, desc)
    def __getattr__(self, name):
        return getattr(self._cursor, name)


class _NoOpCursor:
    """Minimal cursor stub returned when executescript has no real statements."""
    description = []
    def fetchone(self): return None
    def fetchall(self): return []
    def fetchmany(self, n): return []
    @property
    def rowcount(self): return -1


class LibSQLConnectionProxy:
    """Drop-in proxy for a libsql Connection.

    Wraps the real connection so callers see a normal Python object with
    ``execute``, ``commit``, ``rollback``, ``close``, ``executescript``, and
    ``executemany``.  Never assigns to attributes of the underlying C-level
    connection — the root cause of the read-only-attribute bug.

    All query results are wrapped via ``_LibSQLCursorWrapper`` so that
    ``row["column"]`` access works identically to ``sqlite3.Row``.
    """
    __slots__ = ("_conn",)

    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        if params is not None:
            cur = self._conn.execute(sql, params)
        else:
            cur = self._conn.execute(sql)
        return _LibSQLCursorWrapper(cur)

    def executemany(self, sql, params_list):
        return _LibSQLCursorWrapper(self._conn.executemany(sql, params_list))

    def executescript(self, sql):
        """Run multiple statements. libsql lacks executescript, so split manually."""
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        last_cursor = None
        for stmt in statements:
            try:
                last_cursor = self._conn.execute(stmt)
            except Exception:
                # Silently skip unsupported PRAGMAs on Turso
                if not stmt.upper().lstrip().startswith("PRAGMA"):
                    raise
        if last_cursor is not None:
            return _LibSQLCursorWrapper(last_cursor)
        # No-op cursor for empty/all-PRAGMA scripts
        return _NoOpCursor()

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def cursor(self):
        return _LibSQLCursorWrapper(self._conn.cursor())

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()
        return False


class MemoryRepository:
    """SQLite-backed memory with connection-per-operation.

    Thread-safe, transactional, no shared connections.
    """

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or DATA_DIR / "nally_memory.db"
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._schema_initialized = False
        self._working: Dict[str, Any] = {}

    def _create_connection(self):
        """Create a fresh connection. Uses Turso/LibSQL if TURSO_URL is set, else local SQLite."""
        if TURSO_URL and TURSO_TOKEN:
            import libsql_experimental as libsql
            raw = libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN)
            return LibSQLConnectionProxy(raw)
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

    def _ensure_schema(self, conn):
        """Create tables if they don't exist. Runs once per connection."""
        if not self._schema_initialized:
            self._backfill_expires_at(conn)
            # libsql doesn't support executescript — run statements individually
            if TURSO_URL and TURSO_TOKEN:
                for stmt in _SCHEMA.split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        try:
                            conn.execute(stmt)
                        except Exception:
                            pass  # table already exists
            else:
                conn.executescript(_SCHEMA)
            self._schema_initialized = True
            self._backfill_fts(conn)

    def _backfill_fts(self, conn: sqlite3.Connection):
        """Populate FTS index from existing memories (one-time, idempotent)."""
        try:
            fts_count = conn.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0]
            mem_count = conn.execute("SELECT COUNT(*) FROM memories WHERE deleted = 0").fetchone()[0]
            if fts_count < mem_count:
                conn.execute(
                    "INSERT INTO memories_fts(rowid, key, value, category) SELECT id, key, value, category FROM memories WHERE deleted = 0 AND id NOT IN (SELECT rowid FROM memories_fts)"
                )
        except Exception:
            pass  # FTS table might not exist yet on older DBs

    def _fts_search(self, conn, search: str, min_confidence: float, limit: int):
        """Search memories using FTS5 tokenized matching. Returns rows or None if FTS unavailable."""
        try:
            # Tokenize query: split on non-alphanumeric, join with OR
            import re
            tokens = [t for t in re.split(r'[^a-zA-Z0-9_]+', search) if len(t) >= 2]
            if not tokens:
                return None
            fts_query = " OR ".join(tokens)
            rows = conn.execute(
                """SELECT m.* FROM memories m
                   JOIN memories_fts f ON m.id = f.rowid
                   WHERE memories_fts MATCH ? AND m.deleted = 0 AND m.confidence >= ?
                   ORDER BY m.confidence DESC LIMIT ?""",
                (fts_query, min_confidence, limit),
            ).fetchall()
            return rows
        except Exception:
            return None  # Fall back to LIKE

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat()

    # ── Long-term Memory ──────────────────────────────────────

    def remember(self, key: str, value: str, category: str = "general", confidence: float = 0.5, ttl_days: Optional[int] = None) -> str:
        """Store a fact. Boosts confidence if key already exists.

        Args:
            ttl_days: If set, memory auto-expires after this many days.
        """
        if not key.strip() or not str(value).strip():
            return f"Error: key and value are required and must be non-empty. Got key='{key}' value='{value}'"
        # Warn when storing profile facts with unrecognized keys
        if category == "profile" and key not in RECOGNIZED_PROFILE_KEYS:
            import logging

            logging.getLogger("nally.memory").warning(
                f"Profile fact '{key}' is not a recognized profile key. "
                f"Recognized keys: {', '.join(sorted(RECOGNIZED_PROFILE_KEYS))}"
            )
        now = self._now()
        expires_at = None
        if ttl_days is not None:
            expires_at = (datetime.now() + timedelta(days=ttl_days)).isoformat()
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT id, confidence, mention_count FROM memories WHERE key = ? AND deleted = 0",
                (key,),
            ).fetchone()

            if existing:
                new_confidence = boost_confidence(existing["confidence"], 0.1)
                new_count = existing["mention_count"] + 1
                if expires_at:
                    conn.execute(
                        "UPDATE memories SET value = ?, category = ?, confidence = ?, mention_count = ?, last_confirmed = ?, expires_at = ? WHERE id = ?",
                        (value, category, new_confidence, new_count, now, expires_at, existing["id"]),
                    )
                else:
                    conn.execute(
                        "UPDATE memories SET value = ?, category = ?, confidence = ?, mention_count = ?, last_confirmed = ? WHERE id = ?",
                        (value, category, new_confidence, new_count, now, existing["id"]),
                    )
                return f"Updated: {key} = {value} (confidence: {new_confidence:.1f}, mentions: {new_count})"
            else:
                conn.execute(
                    "INSERT INTO memories (key, value, category, confidence, mention_count, created, last_confirmed, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (key, value, category, confidence, 1, now, now, expires_at),
                )
                return f"Remembered: {key} = {value}"

    def recall(
        self,
        key: Optional[str] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 20,
        include_expired: bool = False,
    ) -> Any:
        """Recall memories with confidence filtering.

        Args:
            include_expired: If False (default), skip memories past expires_at.
        """
        expired_clause = "" if include_expired else "AND (expires_at IS NULL OR expires_at > ?)"
        now_iso = self._now()

        with self._connection() as conn:
            if key:
                row = conn.execute(
                    f"SELECT * FROM memories WHERE key = ? AND deleted = 0 {expired_clause}",
                    (key, now_iso) if not include_expired else (key,),
                ).fetchone()
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
                    f"SELECT * FROM memories WHERE category = ? AND deleted = 0 AND confidence >= ? {expired_clause} ORDER BY confidence DESC, last_confirmed DESC LIMIT ?",
                    (category, min_confidence, now_iso, limit) if not include_expired else (category, min_confidence, limit),
                ).fetchall()
                return {row["key"]: row["value"] for row in rows}

            if search:
                # FTS5 tokenized search with LIKE fallback
                rows = self._fts_search(conn, search, min_confidence, limit)
                if rows:
                    return {row["key"]: row["value"] for row in rows}
                # Fallback to LIKE if FTS unavailable or empty
                like_pattern = f"%{search}%"
                rows = conn.execute(
                    f"SELECT * FROM memories WHERE deleted = 0 AND confidence >= ? AND (key LIKE ? OR value LIKE ? OR category LIKE ?) {expired_clause} ORDER BY confidence DESC LIMIT ?",
                    (min_confidence, like_pattern, like_pattern, like_pattern, now_iso, limit) if not include_expired else (min_confidence, like_pattern, like_pattern, like_pattern, limit),
                ).fetchall()
                return {row["key"]: row["value"] for row in rows}

            # Return all high-confidence memories
            rows = conn.execute(
                f"SELECT * FROM memories WHERE deleted = 0 AND confidence >= ? {expired_clause} ORDER BY confidence DESC, last_confirmed DESC LIMIT ?",
                (min_confidence, now_iso, limit) if not include_expired else (min_confidence, limit),
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

    def prune_expired(self) -> int:
        """Soft-delete memories past their expires_at date. Returns count pruned."""
        now = datetime.now().isoformat()
        with self._connection() as conn:
            cursor = conn.execute(
                "UPDATE memories SET deleted = 1 WHERE deleted = 0 AND expires_at IS NOT NULL AND expires_at < ?",
                (now,),
            )
            return cursor.rowcount

    def _backfill_expires_at(self, conn: sqlite3.Connection):
        """Add expires_at column if missing (backward compat for existing DBs)."""
        _backfill_expires_at_column(conn)

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

    def get_recent_episodes_text(self, limit: int = 3) -> str:
        """Get recent episodes as formatted text for system prompt injection."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT topic, outcome, date FROM episodes WHERE topic != 'daily_reflection' ORDER BY date DESC LIMIT ?",
                (limit,),
            ).fetchall()
        if not rows:
            return ""
        lines = []
        for r in rows:
            date_str = r["date"][:10] if r["date"] else "?"
            outcome = (r["outcome"] or "")[:80]
            lines.append(f"- [{date_str}] {r['topic']}: {outcome}")
        return "Recent activity:\n" + "\n".join(lines)

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

    def merge_sessions_into(
        self,
        source_session_ids: List[str],
        target_session_id: str,
        limit: int = 200,
    ) -> int:
        """Copy messages from old per-channel sessions into the unified one.

        Time-sorted across sources, capped at the last `limit` messages.
        Skipped entirely when the target already has history (idempotent) or
        no source rows exist. Old rows are left in place. Returns count copied.
        """
        if not source_session_ids:
            return 0
        with self._connection() as conn:
            existing = conn.execute(
                "SELECT COUNT(*) FROM conversation_messages WHERE session_id = ?",
                (target_session_id,),
            ).fetchone()[0]
            if existing:
                return 0
            placeholders = ",".join("?" * len(source_session_ids))
            rows = conn.execute(
                f"SELECT role, content, tool_calls, tool_call_id FROM conversation_messages "
                f"WHERE session_id IN ({placeholders}) ORDER BY timestamp ASC, id ASC",
                tuple(source_session_ids),
            ).fetchall()
            if not rows:
                return 0
            rows = rows[-limit:]
            now = self._now()
            conn.executemany(
                "INSERT INTO conversation_messages (session_id, role, content, tool_calls, tool_call_id, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                [
                    (target_session_id, r["role"], r["content"], r["tool_calls"], r["tool_call_id"], now)
                    for r in rows
                ],
            )
            return len(rows)

    def get_last_session_id(self) -> Optional[str]:
        """Get the most recent session ID."""
        with self._connection() as conn:
            try:
                row = conn.execute("SELECT session_id FROM conversation_messages ORDER BY id DESC LIMIT 1").fetchone()
                return row["session_id"] if row else None
            except sqlite3.OperationalError:
                return None

    # ── Execution Tracing ────────────────────────────────────

    def save_span(self, span: dict) -> None:
        """Persist a completed span. Called by Tracer. Full JSON, no truncation."""
        with self._connection() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO spans
                   (span_id, parent_span_id, run_id, name, status,
                    input_json, output_json, error, started_at, ended_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    span["span_id"],
                    span.get("parent_span_id"),
                    span.get("run_id", ""),
                    span.get("name", ""),
                    span.get("status", "ok"),
                    json.dumps(span.get("input") or {}, default=str),
                    json.dumps(span.get("output"), default=str) if span.get("output") is not None else None,
                    span.get("error"),
                    span.get("started_at", 0),
                    span.get("ended_at"),
                ),
            )

    def get_spans_by_run(self, run_id: str) -> List[Dict[str, Any]]:
        """Get all spans for a run_id, ordered by start time. Parses JSON columns."""
        with self._connection() as conn:
            rows = conn.execute(
                "SELECT * FROM spans WHERE run_id = ? ORDER BY started_at",
                (run_id,),
            ).fetchall()
        return [self._span_to_dict(r) for r in rows]

    def list_recent_runs(self, limit: int = 50) -> List[Dict[str, Any]]:
        """List recent run_ids with a one-line summary for browsing."""
        with self._connection() as conn:
            rows = conn.execute(
                """SELECT run_id,
                          MIN(started_at) AS started,
                          MAX(COALESCE(ended_at, started_at)) AS ended,
                          COUNT(*) AS span_count,
                          SUM(CASE WHEN status = 'error' THEN 1 ELSE 0 END) AS error_count
                   FROM spans
                   GROUP BY run_id
                   ORDER BY started DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
            results = []
            for r in rows:
                d = dict(r)
                d["tool_count"] = conn.execute(
                    "SELECT COUNT(*) AS c FROM spans WHERE run_id = ? AND name LIKE 'tool:%'", (d["run_id"],)
                ).fetchone()["c"]
                d["started"] = d.get("started")
                d["ended"] = d.get("ended")
                d["duration_ms"] = (
                    round((d["ended"] - d["started"]) * 1000, 1) if d.get("ended") and d.get("started") else None
                )
                results.append(d)
        return results

    def prune_spans(self, keep_days: int = 30) -> int:
        """Delete spans older than keep_days. Explicit maintenance — NOT auto-run."""
        import time as _time

        cutoff = _time.time() - (keep_days * 86400)
        with self._connection() as conn:
            cursor = conn.execute("DELETE FROM spans WHERE started_at < ?", (cutoff,))
            return cursor.rowcount

    @staticmethod
    def _span_to_dict(row) -> Dict[str, Any]:
        """Convert an sqlite3.Row span to a dict with parsed JSON columns."""
        d = dict(row)
        try:
            d["input"] = json.loads(d.get("input_json") or "{}")
        except (json.JSONDecodeError, ValueError):
            d["input"] = {}
        try:
            d["output"] = json.loads(d["output_json"]) if d.get("output_json") else None
        except (json.JSONDecodeError, ValueError):
            d["output"] = None
        d.pop("input_json", None)
        d.pop("output_json", None)
        d["duration_ms"] = (
            round((d["ended_at"] - d["started_at"]) * 1000, 1)
            if d.get("ended_at") and d.get("started_at")
            else None
        )
        return d


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
            "description": "Store a fact or record an episode. Use type=fact for preferences, facts, people (requires key+value). Use type=episode for experiences, debugging sessions, lessons learned (requires topic+what_happened).",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "A short label — required for type=fact only (e.g. 'favorite_color'). Ignored for type=episode.",
                    },
                    "value": {
                        "type": "string",
                        "description": "The information to remember — required for type=fact only. Ignored for type=episode.",
                    },
                    "category": {
                        "type": "string",
                        "description": "Category for organization — type=fact only. Ignored for type=episode.",
                        "enum": ["general", "preference", "task", "people", "project", "goal", "habit", "fact"],
                    },
                    "type": {
                        "type": "string",
                        "enum": ["fact", "episode"],
                        "description": "fact = store a preference/fact, episode = record an experience",
                    },
                    "topic": {
                        "type": "string",
                        "description": "Short topic label — required for type=episode only (e.g. 'Render deployment fix'). Ignored for type=fact.",
                    },
                    "what_happened": {
                        "type": "string",
                        "description": "What happened — required for type=episode only. Ignored for type=fact.",
                    },
                    "outcome": {
                        "type": "string",
                        "description": "What was the result — type=episode only. Ignored for type=fact.",
                    },
                    "solution": {
                        "type": "string",
                        "description": "How it was resolved — type=episode only. Ignored for type=fact.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags for search — type=episode only. Ignored for type=fact.",
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
            "description": "Retrieve facts or episodes from memory. Use type=fact for preferences/facts (use key or search). Use type=episode for past experiences (use topic or search).",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "The exact key to look up — type=fact only. Ignored for type=episode.",
                    },
                    "category": {
                        "type": "string",
                        "description": "Filter by category — type=fact only. Ignored for type=episode.",
                    },
                    "search": {
                        "type": "string",
                        "description": "Search across memories by keyword (works for both fact and episode types)",
                    },
                    "type": {
                        "type": "string",
                        "enum": ["fact", "episode"],
                        "description": "fact = retrieve preferences/facts, episode = retrieve past experiences",
                    },
                    "topic": {
                        "type": "string",
                        "description": "Filter by topic — type=episode only. Ignored for type=fact.",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget",
            "description": "Soft-delete a fact from memory (hidden from queries but recoverable from DB). Only works on facts — cannot delete episodes, conversations, or semantic patterns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": "The fact key to forget",
                    },
                },
                "required": ["key"],
            },
        },
    },
]



