"""Nally Redis Cache — Layerbase REST or self-hosted Redis.

Supports:
- Layerbase REST API (Upstash-compatible)
- Self-hosted Redis via redis-py

Usage:
    from nally.db.redis import get_cache
    cache = get_cache()
    if cache:
        await cache.set("key", "value", ex=3600)
        value = await cache.get("key")
"""

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger("nally.db.redis")


class RedisCache:
    """Redis cache with Layerbase REST or redis-py backend."""

    def __init__(self, url: str = "", token: str = ""):
        self._url = url
        self._token = token
        self._client = None
        self._is_rest = "layerbase" in url.lower() or "upstash" in url.lower()

    async def _ensure_client(self):
        """Create client if not exists."""
        if self._client is not None:
            return

        if self._is_rest:
            # Layerbase REST API (Upstash-compatible)
            try:
                import httpx
                self._client = httpx.AsyncClient(
                    base_url=self._url,
                    headers={
                        "Authorization": f"Bearer {self._token}",
                        "Content-Type": "application/json",
                    },
                    timeout=10.0,
                )
                logger.info("Redis REST client created (Layerbase)")
            except ImportError:
                raise RuntimeError("httpx not installed. Run: pip install httpx")
        else:
            # Self-hosted Redis via redis-py
            try:
                import redis.asyncio as aioredis
                self._client = aioredis.from_url(
                    self._url,
                    decode_responses=True,
                    socket_timeout=5,
                )
                logger.info("Redis client created")
            except ImportError:
                raise RuntimeError("redis not installed. Run: pip install redis")

    async def get(self, key: str) -> Optional[str]:
        """Get a value by key."""
        await self._ensure_client()

        if self._is_rest:
            resp = await self._client.post("/execute", json={
                "commands": [["GET", key]],
            })
            if resp.status_code == 200:
                result = resp.json()
                return result.get("result", [None])[0]
            return None
        else:
            return await self._client.get(key)

    async def set(self, key: str, value: str, ex: Optional[int] = None) -> bool:
        """Set a key-value pair."""
        await self._ensure_client()

        if self._is_rest:
            cmd = ["SET", key, value]
            if ex:
                cmd.extend(["EX", str(ex)])
            resp = await self._client.post("/execute", json={
                "commands": [cmd],
            })
            return resp.status_code == 200
        else:
            return await self._client.set(key, value, ex=ex)

    async def delete(self, key: str) -> bool:
        """Delete a key."""
        await self._ensure_client()

        if self._is_rest:
            resp = await self._client.post("/execute", json={
                "commands": [["DEL", key]],
            })
            return resp.status_code == 200
        else:
            return await self._client.delete(key) > 0

    async def exists(self, key: str) -> bool:
        """Check if a key exists."""
        await self._ensure_client()

        if self._is_rest:
            resp = await self._client.post("/execute", json={
                "commands": [["EXISTS", key]],
            })
            if resp.status_code == 200:
                result = resp.json()
                return result.get("result", [0])[0] > 0
            return False
        else:
            return await self._client.exists(key) > 0

    async def incr(self, key: str) -> int:
        """Increment a counter."""
        await self._ensure_client()

        if self._is_rest:
            resp = await self._client.post("/execute", json={
                "commands": [["INCR", key]],
            })
            if resp.status_code == 200:
                result = resp.json()
                return result.get("result", [0])[0]
            return 0
        else:
            return await self._client.incr(key)

    async def expire(self, key: str, seconds: int) -> bool:
        """Set expiry on a key."""
        await self._ensure_client()

        if self._is_rest:
            resp = await self._client.post("/execute", json={
                "commands": [["EXPIRE", key, str(seconds)]],
            })
            return resp.status_code == 200
        else:
            return await self._client.expire(key, seconds)

    async def health_check(self) -> dict:
        """Check Redis connectivity."""
        try:
            await self._ensure_client()
            if self._is_rest:
                resp = await self._client.post("/execute", json={
                    "commands": [["PING"]],
                })
                if resp.status_code == 200:
                    return {"status": "ok", "engine": "redis", "provider": "layerbase"}
                return {"status": "error", "error": f"HTTP {resp.status_code}"}
            else:
                pong = await self._client.ping()
                return {"status": "ok", "engine": "redis", "provider": "self-hosted"}
        except Exception as e:
            return {"status": "error", "engine": "redis", "error": str(e)}

    async def close(self):
        """Close the client connection."""
        if self._client:
            if self._is_rest:
                await self._client.aclose()
            else:
                await self._client.close()
            self._client = None


# ── Singleton ──────────────────────────────────────────────

_cache: Optional[RedisCache] = None


def get_cache() -> Optional[RedisCache]:
    """Get the Redis cache singleton.

    Returns None if REDIS_URL is not configured.
    """
    global _cache
    if _cache is not None:
        return _cache

    url = os.getenv("REDIS_URL", "")
    token = os.getenv("REDIS_TOKEN", "")

    if not url:
        return None

    _cache = RedisCache(url=url, token=token)
    return _cache
