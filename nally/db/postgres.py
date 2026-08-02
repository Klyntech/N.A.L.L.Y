"""PostgreSQL Database Adapter — Layerbase cloud or self-hosted.

Provides the same interface as MemoryRepository but backed by PostgreSQL.
Uses asyncpg for connection pooling and async operations.

Usage:
    from nally.db.postgres import PostgreSQLDatabase
    db = PostgreSQLDatabase("postgresql://user:pass@host/db")
    await db.remember("key", "value", "category")
"""

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nally.db.postgres")


class PostgreSQLDatabase:
    """PostgreSQL-backed database with connection pooling.

    Thread-safe: uses asyncpg connection pool.
    """

    def __init__(self, database_url: str):
        self._url = database_url
        self._pool = None
        self._initialized = False

    async def _ensure_pool(self):
        """Create connection pool if not exists."""
        if self._pool is not None:
            return

        try:
            import asyncpg

            self._pool = await asyncpg.create_pool(
                self._url,
                min_size=2,
                max_size=10,
                command_timeout=30,
            )
            self._initialized = True
            logger.info("PostgreSQL connection pool created")
        except ImportError:
            raise RuntimeError("asyncpg not installed. Run: pip install asyncpg")
        except Exception as e:
            logger.error(f"Failed to create PostgreSQL pool: {e}")
            raise

    async def _ensure_schema(self):
        """Create tables if they don't exist."""
        if self._initialized:
            return

        await self._ensure_pool()

        schema = """
        CREATE TABLE IF NOT EXISTS memories (
            id SERIAL PRIMARY KEY,
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
            id SERIAL PRIMARY KEY,
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
            id SERIAL PRIMARY KEY,
            summary TEXT NOT NULL,
            topics TEXT DEFAULT '[]',
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            message_count INTEGER DEFAULT 0,
            created TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_convos_start ON conversations(start_date);

        CREATE TABLE IF NOT EXISTS conversation_messages (
            id SERIAL PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            tool_calls TEXT DEFAULT NULL,
            tool_call_id TEXT DEFAULT NULL,
            timestamp TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_conv_msg_session ON conversation_messages(session_id);
        """

        async with self._pool.acquire() as conn:
            await conn.execute(schema)
        self._initialized = True
        logger.info("PostgreSQL schema initialized")

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat()

    # ── Long-term Memory ──────────────────────────────────

    async def remember(self, key: str, value: str, category: str = "general") -> str:
        """Store a fact. Boosts confidence if key already exists."""
        await self._ensure_schema()
        now = self._now()

        async with self._pool.acquire() as conn:
            # Check if key exists
            row = await conn.fetchrow(
                "SELECT id, confidence, mention_count FROM memories WHERE key = $1 AND deleted = 0",
                key,
            )

            if row:
                new_confidence = min(1.0, row["confidence"] + 0.1)
                new_count = row["mention_count"] + 1
                await conn.execute(
                    "UPDATE memories SET value = $1, category = $2, confidence = $3, mention_count = $4, last_confirmed = $5 WHERE id = $6",
                    value, category, new_confidence, new_count, now, row["id"],
                )
                return f"Updated: {key} = {value} (confidence: {new_confidence:.1f}, mentions: {new_count})"
            else:
                await conn.execute(
                    "INSERT INTO memories (key, value, category, confidence, mention_count, created, last_confirmed) VALUES ($1, $2, $3, 0.5, 1, $4, $4)",
                    key, value, category, now,
                )
                return f"Remembered: {key} = {value}"

    async def recall(
        self,
        key: Optional[str] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
        min_confidence: float = 0.0,
        limit: int = 20,
    ) -> Any:
        """Recall memories with confidence filtering."""
        await self._ensure_schema()

        async with self._pool.acquire() as conn:
            if key:
                row = await conn.fetchrow(
                    "SELECT * FROM memories WHERE key = $1 AND deleted = 0", key
                )
                if row:
                    # Boost confidence on recall
                    await conn.execute(
                        "UPDATE memories SET confidence = LEAST(1.0, confidence + 0.05), last_confirmed = $1 WHERE id = $2",
                        self._now(), row["id"],
                    )
                    return row["value"]
                return None

            if category:
                rows = await conn.fetch(
                    "SELECT * FROM memories WHERE category = $1 AND deleted = 0 AND confidence >= $2 ORDER BY confidence DESC, last_confirmed DESC LIMIT $3",
                    category, min_confidence, limit,
                )
                return {row["key"]: row["value"] for row in rows}

            if search:
                like_pattern = f"%{search}%"
                rows = await conn.fetch(
                    "SELECT * FROM memories WHERE deleted = 0 AND confidence >= $1 AND (key LIKE $2 OR value LIKE $2 OR category LIKE $2) ORDER BY confidence DESC LIMIT $3",
                    min_confidence, like_pattern, limit,
                )
                return {row["key"]: row["value"] for row in rows}

            # Return all high-confidence memories
            rows = await conn.fetch(
                "SELECT * FROM memories WHERE deleted = 0 AND confidence >= $1 ORDER BY confidence DESC, last_confirmed DESC LIMIT $2",
                min_confidence, limit,
            )
            return {row["key"]: row["value"] for row in rows}

    async def forget(self, key: str) -> str:
        """Soft delete a memory."""
        await self._ensure_schema()

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT id FROM memories WHERE key = $1 AND deleted = 0", key
            )
            if row:
                await conn.execute("UPDATE memories SET deleted = 1 WHERE id = $1", row["id"])
                return f"Forgot: {key}"
            return f"Don't remember: {key}"

    async def get_memory_stats(self) -> Dict[str, Any]:
        """Get statistics about stored memories."""
        await self._ensure_schema()

        async with self._pool.acquire() as conn:
            row = await conn.fetchrow("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN confidence >= 0.8 THEN 1 ELSE 0 END) as high_conf,
                    SUM(CASE WHEN confidence < 0.5 THEN 1 ELSE 0 END) as low_conf
                FROM memories WHERE deleted = 0
            """)

            by_cat = await conn.fetch(
                "SELECT category, COUNT(*) as c FROM memories WHERE deleted = 0 GROUP BY category"
            )

            return {
                "total_memories": row["total"],
                "by_category": {r["category"]: r["c"] for r in by_cat},
                "high_confidence": row["high_conf"] or 0,
                "low_confidence": row["low_conf"] or 0,
            }

    async def decay_old_memories(self):
        """Decay confidence for memories not confirmed in a while."""
        await self._ensure_schema()

        from ..memory.confidence import days_since, decay_confidence

        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT id, last_confirmed FROM memories WHERE deleted = 0")
            for row in rows:
                days = days_since(row["last_confirmed"])
                factor = decay_confidence(days)
                if factor < 1.0:
                    await conn.execute(
                        "UPDATE memories SET confidence = confidence * $1 WHERE id = $2",
                        factor, row["id"],
                    )

    # ── Episodic Memory ───────────────────────────────────

    async def add_episode(
        self,
        topic: str,
        what_happened: str,
        outcome: str = "",
        solution: str = "",
        tags: Optional[List[str]] = None,
    ) -> str:
        """Record an experience."""
        await self._ensure_schema()
        now = self._now()

        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO episodes (date, topic, what_happened, outcome, solution, tags, created) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                now, topic, what_happened, outcome, solution, json.dumps(tags or []), now,
            )
        return f"Episode recorded: {topic}"

    async def search_episodes(
        self,
        topic: Optional[str] = None,
        search: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: int = 10,
    ) -> List[Dict]:
        """Search episodic memory."""
        await self._ensure_schema()

        async with self._pool.acquire() as conn:
            if topic:
                rows = await conn.fetch(
                    "SELECT * FROM episodes WHERE topic LIKE $1 ORDER BY date DESC LIMIT $2",
                    f"%{topic}%", limit,
                )
            elif search:
                like = f"%{search}%"
                rows = await conn.fetch(
                    "SELECT * FROM episodes WHERE what_happened LIKE $1 OR topic LIKE $1 OR solution LIKE $1 ORDER BY date DESC LIMIT $2",
                    like, limit,
                )
            else:
                rows = await conn.fetch("SELECT * FROM episodes ORDER BY date DESC LIMIT $1", limit)

            return [dict(row) for row in rows]

    # ── Conversation Memory ───────────────────────────────

    async def save_conversation(
        self,
        summary: str,
        topics: Optional[List[str]] = None,
        start_date: Optional[str] = None,
        message_count: int = 0,
    ) -> str:
        """Save a conversation summary."""
        await self._ensure_schema()
        now = self._now()

        async with self._pool.acquire() as conn:
            await conn.execute(
                "INSERT INTO conversations (summary, topics, start_date, end_date, message_count, created) VALUES ($1, $2, $3, $4, $5, $6)",
                summary, json.dumps(topics or []), start_date or now, now, message_count, now,
            )
        return "Conversation saved"

    async def get_recent_conversations(self, limit: int = 5) -> List[Dict]:
        """Get recent conversation summaries for context injection."""
        await self._ensure_schema()

        async with self._pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM conversations ORDER BY end_date DESC LIMIT $1", limit)
            return [dict(row) for row in rows]

    # ── Conversation History Persistence ──────────────────

    async def save_messages(self, messages: List[Dict[str, Any]], session_id: str = "default") -> str:
        """Save full conversation messages to database."""
        await self._ensure_schema()
        now = self._now()

        async with self._pool.acquire() as conn:
            # Clear old messages for this session
            await conn.execute("DELETE FROM conversation_messages WHERE session_id = $1", session_id)

            # Bulk insert
            for msg in messages:
                await conn.execute(
                    "INSERT INTO conversation_messages (session_id, role, content, tool_calls, tool_call_id, timestamp) VALUES ($1, $2, $3, $4, $5, $6)",
                    session_id,
                    msg.get("role", "user"),
                    msg.get("content", ""),
                    json.dumps(msg.get("tool_calls")) if msg.get("tool_calls") else None,
                    msg.get("tool_call_id"),
                    now,
                )
        return f"Saved {len(messages)} messages"

    async def load_messages(self, session_id: str = "default") -> List[Dict[str, Any]]:
        """Load conversation messages from database."""
        await self._ensure_schema()

        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT role, content, tool_calls, tool_call_id FROM conversation_messages WHERE session_id = $1 ORDER BY id",
                session_id,
            )

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

    # ── Health Check ──────────────────────────────────────

    async def health_check(self) -> Dict[str, Any]:
        """Check database connectivity and return status."""
        try:
            await self._ensure_pool()
            async with self._pool.acquire() as conn:
                await conn.fetchval("SELECT 1")
            return {"status": "ok", "engine": "postgresql", "pool_size": self._pool.get_size()}
        except Exception as e:
            return {"status": "error", "engine": "postgresql", "error": str(e)}

    # ── Sync wrappers (for non-async code) ────────────────

    def remember_sync(self, key: str, value: str, category: str = "general") -> str:
        """Sync wrapper for remember()."""
        import asyncio
        return asyncio.run(self.remember(key, value, category))

    def recall_sync(self, **kwargs) -> Any:
        """Sync wrapper for recall()."""
        import asyncio
        return asyncio.run(self.recall(**kwargs))

    def forget_sync(self, key: str) -> str:
        """Sync wrapper for forget()."""
        import asyncio
        return asyncio.run(self.forget(key))

    def add_episode_sync(self, **kwargs) -> str:
        """Sync wrapper for add_episode()."""
        import asyncio
        return asyncio.run(self.add_episode(**kwargs))

    def search_episodes_sync(self, **kwargs) -> List[Dict]:
        """Sync wrapper for search_episodes()."""
        import asyncio
        return asyncio.run(self.search_episodes(**kwargs))

    def save_messages_sync(self, messages: List[Dict], session_id: str = "default") -> str:
        """Sync wrapper for save_messages()."""
        import asyncio
        return asyncio.run(self.save_messages(messages, session_id))

    def load_messages_sync(self, session_id: str = "default") -> List[Dict]:
        """Sync wrapper for load_messages()."""
        import asyncio
        return asyncio.run(self.load_messages(session_id))
