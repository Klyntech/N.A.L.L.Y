"""Nally Database Layer — abstraction over SQLite, PostgreSQL, and Redis.

Supports:
- SQLite (local, default)
- PostgreSQL (Layerbase cloud)
- Redis (Layerbase REST or self-hosted)

Usage:
    from nally.db import get_db, get_cache
    db = get_db()  # Returns SQLite or PostgreSQL adapter
    cache = get_cache()  # Returns Redis client or None
"""

from .postgres import PostgreSQLDatabase
from .redis import RedisCache, get_cache

# Database backend singleton
_db = None


def get_db():
    """Get the database adapter based on config.

    Returns PostgreSQLDatabase if DATABASE_URL starts with postgresql://,
    otherwise returns the existing SQLite-based MemoryRepository.
    """
    global _db
    if _db is not None:
        return _db

    import os
    from ..config import DATABASE_URL

    if DATABASE_URL and DATABASE_URL.startswith(("postgresql://", "postgres://")):
        _db = PostgreSQLDatabase(DATABASE_URL)
    else:
        # Fall back to existing SQLite store
        from ..memory.store import MemoryRepository
        _db = MemoryRepository()

    return _db


__all__ = ["get_db", "get_cache", "PostgreSQLDatabase", "RedisCache"]
