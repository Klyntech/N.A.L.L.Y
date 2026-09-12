"""Master Database — user registry and OAuth token storage.

Master DB schema (single Neon DB):
  - users: telegram_id, name, username, created_at
  - oauth_tokens: telegram_id, provider, access_token, refresh_token, expires_at
"""

import time
from contextlib import contextmanager
from typing import Any, Dict, List, Optional, Tuple

from ..config import DATABASE_URL, LAYERBASE_API_KEY, LAYERBASE_DB_ID
from ..utils.logger import logger

# Postgres-only (Neon)
_MASTER_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    telegram_id BIGINT PRIMARY KEY,
    username TEXT DEFAULT '',
    first_name TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    last_active TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS oauth_tokens (
    id SERIAL PRIMARY KEY,
    telegram_id BIGINT NOT NULL,
    provider TEXT NOT NULL,
    access_token TEXT NOT NULL,
    refresh_token TEXT DEFAULT NULL,
    expires_at TEXT DEFAULT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(telegram_id, provider)
);
CREATE INDEX IF NOT EXISTS idx_oauth_telegram ON oauth_tokens(telegram_id);
CREATE INDEX IF NOT EXISTS idx_oauth_provider ON oauth_tokens(provider);
"""


def _get_master_url() -> str:
    """Get the master Neon DB connection URL."""
    if LAYERBASE_API_KEY and LAYERBASE_DB_ID:
        # Layerbase REST → direct Postgres URL pattern
        return f"postgresql://lbase:{LAYERBASE_API_KEY}@ep-{LAYERBASE_DB_ID}.pooler.supabase.com:6543/postgres"
    return DATABASE_URL


def _pg_translate(sql: str) -> str:
    """SQLite→Postgres compat: ? → %s, MIN → LEAST."""
    sql = sql.replace("?", "%s")
    sql = sql.replace("MIN(1.0,", "LEAST(1.0,")
    return sql


class MasterDB:
    """Thread-safe, connection-per-operation master DB for user registry + OAuth."""

    def __init__(self):
        self._conn_cache: Dict[int, Any] = {}

    def _connect(self):
        import psycopg2
        url = _get_master_url()
        conn = psycopg2.connect(url)
        conn.autocommit = True
        return conn

    def ensure_schema(self):
        """Create master tables if they don't exist."""
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(_MASTER_SCHEMA)
            cur.close()
            logger.info("Master DB schema ensured")
        finally:
            conn.close()

    # ── Users ──────────────────────────────────────────────

    def upsert_user(self, telegram_id: int, username: str = "", first_name: str = "") -> None:
        """Insert or update a Telegram user."""
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO users (telegram_id, username, first_name, created_at, last_active)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (telegram_id) DO UPDATE SET
                    username = EXCLUDED.username,
                    first_name = EXCLUDED.first_name,
                    last_active = EXCLUDED.last_active
                """,
                (telegram_id, username, first_name, now, now),
            )
            cur.close()
        finally:
            conn.close()

    def get_user(self, telegram_id: int) -> Optional[Dict[str, Any]]:
        """Get user by Telegram ID."""
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT telegram_id, username, first_name, created_at, last_active FROM users WHERE telegram_id = %s", (telegram_id,))
            row = cur.fetchone()
            cur.close()
            if row:
                return {
                    "telegram_id": row[0],
                    "username": row[1],
                    "first_name": row[2],
                    "created_at": row[3],
                    "last_active": row[4],
                }
            return None
        finally:
            conn.close()

    def list_users(self) -> List[Dict[str, Any]]:
        """List all users."""
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT telegram_id, username, first_name, created_at, last_active FROM users ORDER BY last_active DESC")
            rows = cur.fetchall()
            cur.close()
            return [
                {"telegram_id": r[0], "username": r[1], "first_name": r[2], "created_at": r[3], "last_active": r[4]}
                for r in rows
            ]
        finally:
            conn.close()

    # ── OAuth Tokens ───────────────────────────────────────

    def save_oauth_token(
        self, telegram_id: int, provider: str, access_token: str,
        refresh_token: str = None, expires_at: str = None,
    ) -> None:
        """Save or update an OAuth token for a user."""
        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO oauth_tokens (telegram_id, provider, access_token, refresh_token, expires_at, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (telegram_id, provider) DO UPDATE SET
                    access_token = EXCLUDED.access_token,
                    refresh_token = EXCLUDED.refresh_token,
                    expires_at = EXCLUDED.expires_at,
                    updated_at = EXCLUDED.updated_at
                """,
                (telegram_id, provider, access_token, refresh_token, expires_at, now, now),
            )
            cur.close()
        finally:
            conn.close()

    def get_oauth_token(self, telegram_id: int, provider: str) -> Optional[Dict[str, Any]]:
        """Get OAuth token for a user+provider."""
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT access_token, refresh_token, expires_at, created_at, updated_at FROM oauth_tokens WHERE telegram_id = %s AND provider = %s",
                (telegram_id, provider),
            )
            row = cur.fetchone()
            cur.close()
            if row:
                return {
                    "access_token": row[0],
                    "refresh_token": row[1],
                    "expires_at": row[2],
                    "created_at": row[3],
                    "updated_at": row[4],
                }
            return None
        finally:
            conn.close()

    def delete_oauth_token(self, telegram_id: int, provider: str) -> bool:
        """Delete an OAuth token."""
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("DELETE FROM oauth_tokens WHERE telegram_id = %s AND provider = %s", (telegram_id, provider))
            deleted = cur.rowcount > 0
            cur.close()
            return deleted
        finally:
            conn.close()

    def get_user_oauth_providers(self, telegram_id: int) -> List[str]:
        """List OAuth providers connected for a user."""
        conn = self._connect()
        try:
            cur = conn.cursor()
            cur.execute("SELECT provider FROM oauth_tokens WHERE telegram_id = %s", (telegram_id,))
            providers = [row[0] for row in cur.fetchall()]
            cur.close()
            return providers
        finally:
            conn.close()


# ── Singleton ──────────────────────────────────────────────

master_db = MasterDB()
