"""Nally Memory System V2 - SQLite backend with confidence scoring

Memory Types:
- Long-term: User facts with confidence scores (0.0-1.0)
- Episodic: Timestamped experiences
- Conversations: Session summaries
- Semantic: Extracted patterns/preferences
- Working: Current task context (in-memory)
"""
import json
import sqlite3
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, List, Dict, Any, Tuple


class MemoryStoreV2:
    """SQLite-backed memory with confidence scoring and semantic search"""

    def __init__(self, db_path: Path = None):
        self.db_path = db_path or Path(__file__).parent.parent.parent / "data" / "nally_memory.db"
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = None
        self._working_memory: Dict[str, Any] = {}
        self._init_db()

    def _get_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            # Try cloud DB first (Turso), fall back to local
            try:
                from .cloud import cloud_db
                self._conn = cloud_db.get_connection(str(self.db_path))
            except Exception:
                self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
                self._conn.row_factory = sqlite3.Row
                self._conn.execute("PRAGMA journal_mode=WAL")
                self._conn.execute("PRAGMA foreign_keys=ON")
        return self._conn

    def _init_db(self):
        conn = self._get_conn()
        conn.executescript("""
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
        """)
        conn.commit()

    def _now(self) -> str:
        return datetime.now().isoformat()

    def _decay_confidence(self, days_since: float) -> float:
        """Decay confidence for old memories not confirmed"""
        if days_since < 7:
            return 1.0
        elif days_since < 30:
            return 0.9
        elif days_since < 90:
            return 0.7
        elif days_since < 180:
            return 0.5
        else:
            return 0.3

    # ── Long-term Memory ──────────────────────────────────────────

    def remember(self, key: str, value: str, category: str = "general") -> str:
        """Store a fact with confidence scoring"""
        conn = self._get_conn()
        now = self._now()

        # Check if key exists (non-deleted)
        existing = conn.execute(
            "SELECT id, confidence, mention_count FROM memories WHERE key = ? AND deleted = 0",
            (key,)
        ).fetchone()

        if existing:
            # Update existing memory: boost confidence, increment count
            new_confidence = min(1.0, existing["confidence"] + 0.1)
            new_count = existing["mention_count"] + 1
            conn.execute(
                "UPDATE memories SET value = ?, category = ?, confidence = ?, mention_count = ?, last_confirmed = ? WHERE id = ?",
                (value, category, new_confidence, new_count, now, existing["id"])
            )
            conn.commit()
            return f"Updated: {key} = {value} (confidence: {new_confidence:.1f}, mentions: {new_count})"
        else:
            # Insert new memory
            conn.execute(
                "INSERT INTO memories (key, value, category, confidence, mention_count, created, last_confirmed) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (key, value, category, 0.5, 1, now, now)
            )
            conn.commit()
            return f"Remembered: {key} = {value}"

    def recall(
        self,
        key: str = None,
        category: str = None,
        search: str = None,
        min_confidence: float = 0.0,
        limit: int = 20
    ) -> Any:
        """Recall memories with confidence filtering and relevance ranking"""
        conn = self._get_conn()
        now = datetime.now()

        if key:
            row = conn.execute(
                "SELECT * FROM memories WHERE key = ? AND deleted = 0", (key,)
            ).fetchone()
            if row:
                # Boost confidence on recall (the fact is still relevant)
                conn.execute(
                    "UPDATE memories SET confidence = MIN(1.0, confidence + 0.05), last_confirmed = ? WHERE id = ?",
                    (self._now(), row["id"])
                )
                conn.commit()
                return row["value"]
            return None

        if category:
            rows = conn.execute(
                "SELECT * FROM memories WHERE category = ? AND deleted = 0 AND confidence >= ? ORDER BY confidence DESC, last_confirmed DESC LIMIT ?",
                (category, min_confidence, limit)
            ).fetchall()
            return {row["key"]: row["value"] for row in rows}

        if search:
            search_lower = search.lower()
            rows = conn.execute(
                "SELECT * FROM memories WHERE deleted = 0 AND confidence >= ?",
                (min_confidence,)
            ).fetchall()
            results = {}
            for row in rows:
                if (search_lower in row["key"].lower() or
                    search_lower in str(row["value"]).lower() or
                    search_lower in row["category"].lower()):
                    results[row["key"]] = row["value"]
            return results

        # Return all high-confidence memories
        rows = conn.execute(
            "SELECT * FROM memories WHERE deleted = 0 AND confidence >= ? ORDER BY confidence DESC, last_confirmed DESC LIMIT ?",
            (min_confidence, limit)
        ).fetchall()
        return {row["key"]: row["value"] for row in rows}

    def forget(self, key: str) -> str:
        """Soft delete a memory"""
        conn = self._get_conn()
        row = conn.execute(
            "SELECT id FROM memories WHERE key = ? AND deleted = 0", (key,)
        ).fetchone()
        if row:
            conn.execute("UPDATE memories SET deleted = 1 WHERE id = ?", (row["id"],))
            conn.commit()
            return f"Forgot: {key}"
        return f"Don't remember: {key}"

    def get_memory_stats(self) -> Dict[str, Any]:
        """Get statistics about stored memories"""
        conn = self._get_conn()
        total = conn.execute("SELECT COUNT(*) as c FROM memories WHERE deleted = 0").fetchone()["c"]
        by_cat = conn.execute(
            "SELECT category, COUNT(*) as c FROM memories WHERE deleted = 0 GROUP BY category"
        ).fetchall()
        high_conf = conn.execute(
            "SELECT COUNT(*) as c FROM memories WHERE deleted = 0 AND confidence >= 0.8"
        ).fetchone()["c"]
        low_conf = conn.execute(
            "SELECT COUNT(*) as c FROM memories WHERE deleted = 0 AND confidence < 0.5"
        ).fetchone()["c"]
        return {
            "total_memories": total,
            "by_category": {row["category"]: row["c"] for row in by_cat},
            "high_confidence": high_conf,
            "low_confidence": low_conf,
        }

    def decay_old_memories(self):
        """Decay confidence for memories not confirmed in a while"""
        conn = self._get_conn()
        now = datetime.now()
        rows = conn.execute("SELECT id, last_confirmed FROM memories WHERE deleted = 0").fetchall()
        for row in rows:
            last = datetime.fromisoformat(row["last_confirmed"])
            days = (now - last).days
            decay = self._decay_confidence(days)
            conn.execute(
                "UPDATE memories SET confidence = confidence * ? WHERE id = ?",
                (decay, row["id"])
            )
        conn.commit()

    # ── Episodic Memory ───────────────────────────────────────────

    def add_episode(
        self,
        topic: str,
        what_happened: str,
        outcome: str = "",
        solution: str = "",
        tags: List[str] = None
    ) -> str:
        """Record an experience"""
        conn = self._get_conn()
        now = self._now()
        conn.execute(
            "INSERT INTO episodes (date, topic, what_happened, outcome, solution, tags, created) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (now, topic, what_happened, outcome, solution, json.dumps(tags or []), now)
        )
        conn.commit()
        return f"Episode recorded: {topic}"

    def search_episodes(
        self,
        topic: str = None,
        search: str = None,
        tags: List[str] = None,
        limit: int = 10
    ) -> List[Dict]:
        """Search episodic memory"""
        conn = self._get_conn()

        if topic:
            rows = conn.execute(
                "SELECT * FROM episodes WHERE topic LIKE ? ORDER BY date DESC LIMIT ?",
                (f"%{topic}%", limit)
            ).fetchall()
        elif search:
            rows = conn.execute(
                "SELECT * FROM episodes WHERE what_happened LIKE ? OR topic LIKE ? OR solution LIKE ? ORDER BY date DESC LIMIT ?",
                (f"%{search}%", f"%{search}%", f"%{search}%", limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM episodes ORDER BY date DESC LIMIT ?", (limit,)
            ).fetchall()

        return [dict(row) for row in rows]

    # ── Conversation Memory ───────────────────────────────────────

    def save_conversation(
        self,
        summary: str,
        topics: List[str] = None,
        start_date: str = None,
        message_count: int = 0
    ) -> str:
        """Save a conversation summary"""
        conn = self._get_conn()
        now = self._now()
        conn.execute(
            "INSERT INTO conversations (summary, topics, start_date, end_date, message_count, created) VALUES (?, ?, ?, ?, ?, ?)",
            (summary, json.dumps(topics or []), start_date or now, now, message_count, now)
        )
        conn.commit()
        return "Conversation saved"

    def get_recent_conversations(self, limit: int = 5) -> List[Dict]:
        """Get recent conversation summaries for context injection"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT * FROM conversations ORDER BY end_date DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(row) for row in rows]

    def get_conversation_summaries_text(self, limit: int = 3) -> str:
        """Get formatted conversation summaries for system prompt injection"""
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

    # ── Semantic Memory ───────────────────────────────────────────

    def add_semantic(self, pattern: str, confidence: float = 0.5) -> str:
        """Add or update a semantic pattern (extracted preference/fact)"""
        conn = self._get_conn()
        now = self._now()

        existing = conn.execute(
            "SELECT id, confidence, evidence_count FROM semantic WHERE pattern = ?",
            (pattern,)
        ).fetchone()

        if existing:
            new_conf = min(1.0, existing["confidence"] + 0.15)
            new_count = existing["evidence_count"] + 1
            conn.execute(
                "UPDATE semantic SET confidence = ?, evidence_count = ?, last_seen = ? WHERE id = ?",
                (new_conf, new_count, now, existing["id"])
            )
            conn.commit()
            return f"Pattern reinforced: {pattern} (confidence: {new_conf:.1f})"
        else:
            conn.execute(
                "INSERT INTO semantic (pattern, confidence, evidence_count, last_seen, created) VALUES (?, ?, ?, ?, ?)",
                (pattern, confidence, 1, now, now)
            )
            conn.commit()
            return f"Pattern learned: {pattern}"

    def recall_semantic(self, search: str = None, min_confidence: float = 0.5) -> List[Dict]:
        """Recall semantic patterns"""
        conn = self._get_conn()
        if search:
            rows = conn.execute(
                "SELECT * FROM semantic WHERE pattern LIKE ? AND confidence >= ? ORDER BY confidence DESC",
                (f"%{search}%", min_confidence)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM semantic WHERE confidence >= ? ORDER BY confidence DESC",
                (min_confidence,)
            ).fetchall()
        return [dict(row) for row in rows]

    # ── Working Memory ────────────────────────────────────────────

    def set_working(self, key: str, value: Any):
        """Set working memory (current task context)"""
        self._working_memory[key] = {
            "value": value,
            "timestamp": time.time()
        }

    def get_working(self, key: str = None) -> Any:
        """Get working memory"""
        if key:
            entry = self._working_memory.get(key)
            return entry["value"] if entry else None
        return {k: v["value"] for k, v in self._working_memory.items()}

    def clear_working(self):
        """Clear all working memory"""
        self._working_memory.clear()

    # ── Profile Integration ───────────────────────────────────────

    def get_user_facts(self) -> str:
        """Get formatted user facts for system prompt injection"""
        conn = self._get_conn()
        rows = conn.execute(
            "SELECT key, value, confidence FROM memories WHERE deleted = 0 AND confidence >= 0.5 ORDER BY confidence DESC LIMIT 30"
        ).fetchall()
        if not rows:
            return "No user facts stored yet."
        lines = []
        for row in rows:
            conf = row["confidence"]
            marker = "*" if conf >= 0.8 else ""
            lines.append(f"- {row['key']}: {row['value']}{marker}")
        return "\n".join(lines)

    # ── Conversation History Persistence ──────────────────────────

    def save_messages(self, messages: List[Dict[str, Any]], session_id: str = "default") -> str:
        """Save full conversation messages to database.

        Args:
            messages: List of message dicts with 'role', 'content', etc.
            session_id: Unique identifier for this conversation session.

        Returns:
            Status message.
        """
        conn = self._get_conn()
        now = self._now()

        # Create messages table if not exists
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversation_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                tool_calls TEXT DEFAULT NULL,
                tool_call_id TEXT DEFAULT NULL,
                timestamp TEXT NOT NULL
            )
        """)
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_conv_msg_session ON conversation_messages(session_id)"
        )

        # Clear old messages for this session
        conn.execute("DELETE FROM conversation_messages WHERE session_id = ?", (session_id,))

        # Insert all messages
        for msg in messages:
            conn.execute(
                "INSERT INTO conversation_messages (session_id, role, content, tool_calls, tool_call_id, timestamp) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    session_id,
                    msg.get("role", "user"),
                    msg.get("content", ""),
                    json.dumps(msg.get("tool_calls")) if msg.get("tool_calls") else None,
                    msg.get("tool_call_id"),
                    now,
                )
            )
        conn.commit()
        return f"Saved {len(messages)} messages"

    def load_messages(self, session_id: str = "default") -> List[Dict[str, Any]]:
        """Load conversation messages from database.

        Args:
            session_id: Unique identifier for this conversation session.

        Returns:
            List of message dicts.
        """
        conn = self._get_conn()

        # Check if table exists
        try:
            conn.execute("SELECT 1 FROM conversation_messages LIMIT 1")
        except sqlite3.OperationalError:
            return []

        rows = conn.execute(
            "SELECT role, content, tool_calls, tool_call_id FROM conversation_messages WHERE session_id = ? ORDER BY id",
            (session_id,)
        ).fetchall()

        messages = []
        for row in rows:
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
        conn = self._get_conn()
        try:
            row = conn.execute(
                "SELECT session_id FROM conversation_messages ORDER BY id DESC LIMIT 1"
            ).fetchone()
            return row["session_id"] if row else None
        except sqlite3.OperationalError:
            return None

    def close(self):
        if self._conn:
            self._conn.close()
            self._conn = None


class MemoryToolsV2:
    """Memory tools for the agent (V2 with enhanced schemas)"""

    def __init__(self, store: MemoryStoreV2):
        self.store = store

    def to_tool_list(self) -> list:
        return [
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


# Singleton
memory_v2 = MemoryStoreV2()
memory_tools_v2 = MemoryToolsV2(memory_v2)
