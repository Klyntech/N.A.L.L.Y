"""Nally Health Check — /health endpoint for Docker, load balancers, monitoring.

Returns system status, database connectivity, and uptime.
No auth required — this is for infrastructure health checks.
"""

import os
import time
from pathlib import Path

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..config import ACTIVE_MODEL, DATA_DIR, DATABASE_URL, PROVIDER

router = APIRouter()

_start_time = time.time()

# ── Version ────────────────────────────────────────────────


def _get_version() -> str:
    """Read version from pyproject.toml or default."""
    try:
        import tomllib

        pyproject = Path(__file__).parent.parent.parent / "pyproject.toml"
        if pyproject.exists():
            with open(pyproject, "rb") as f:
                data = tomllib.load(f)
            return data.get("project", {}).get("version", "0.1.0")
    except Exception:
        pass
    return "0.1.0"


# ── Checkers ───────────────────────────────────────────────


async def _check_database() -> dict:
    """Check database connectivity."""
    # PostgreSQL via Layerbase or self-hosted
    if DATABASE_URL and DATABASE_URL.startswith(("postgresql://", "postgres://")):
        try:
            import asyncpg

            async def _test():
                conn = await asyncpg.connect(DATABASE_URL, timeout=5)
                await conn.fetchval("SELECT 1")
                await conn.close()

            await _test()
            return {"status": "ok", "engine": "postgresql", "url": DATABASE_URL[:40] + "..."}
        except ImportError:
            return {"status": "error", "engine": "postgresql", "error": "asyncpg not installed"}
        except Exception as e:
            return {"status": "error", "engine": "postgresql", "error": str(e)[:100]}

    # Turso/LibSQL
    if DATABASE_URL and DATABASE_URL.startswith("libsql://"):
        return {"status": "ok", "engine": "libsql", "url": DATABASE_URL[:50] + "..."}

    # SQLite (default)
    db_path = DATA_DIR / "nally_memory.db"
    if db_path.exists():
        size_mb = db_path.stat().st_size / (1024 * 1024)
        return {
            "status": "ok",
            "engine": "sqlite",
            "path": str(db_path.name),
            "size_mb": round(size_mb, 2),
        }
    return {"status": "ok", "engine": "sqlite", "note": "will be created on first use"}


async def _check_redis() -> dict:
    """Check Redis connectivity if configured."""
    redis_url = os.getenv("REDIS_URL", "")
    if not redis_url:
        return {"status": "not_configured"}

    # Layerbase REST (Upstash-compatible)
    if "layerbase" in redis_url or "upstash" in redis_url:
        try:
            import httpx

            async def _test():
                token = os.getenv("REDIS_TOKEN", "")
                async with httpx.AsyncClient() as client:
                    resp = await client.post(
                        redis_url.rstrip("/") + "/execute",
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                        },
                        json={"commands": [["PING"]]},
                        timeout=5.0,
                    )
                    return resp.status_code == 200

            ok = await _test()
            return {"status": "ok" if ok else "error", "engine": "redis", "provider": "layerbase"}
        except Exception as e:
            return {"status": "error", "engine": "redis", "provider": "layerbase", "error": str(e)[:100]}

    # Self-hosted Redis
    try:
        import redis.asyncio as aioredis

        async def _test():
            client = aioredis.from_url(redis_url, socket_timeout=5)
            await client.ping()
            await client.close()

        await _test()
        return {"status": "ok", "engine": "redis", "provider": "self-hosted"}
    except ImportError:
        return {"status": "ok", "engine": "redis", "note": "redis package not installed"}
    except Exception as e:
        return {"status": "error", "engine": "redis", "error": str(e)[:100]}


def _check_tools() -> dict:
    """Check loaded tools count."""
    try:
        from ..tools.registry import registry

        return {"status": "ok", "count": len(registry.tools)}
    except Exception:
        return {"status": "not_loaded"}


# ── Endpoint ───────────────────────────────────────────────


@router.get("/health")
async def health_check():
    """Health check endpoint. No auth required.

    Returns:
        200: System healthy
        503: System degraded
    """
    uptime = time.time() - _start_time
    version = _get_version()

    checks = {
        "database": await _check_database(),
        "redis": await _check_redis(),
        "tools": _check_tools(),
    }

    # Determine overall status
    all_ok = all(c.get("status") in ("ok", "not_configured", "not_loaded") for c in checks.values())
    overall = "healthy" if all_ok else "degraded"

    response = {
        "status": overall,
        "version": version,
        "provider": PROVIDER,
        "model": ACTIVE_MODEL,
        "uptime_seconds": round(uptime, 1),
        "uptime_human": _format_uptime(uptime),
        "checks": checks,
    }

    status_code = 200 if all_ok else 503
    return JSONResponse(content=response, status_code=status_code)


@router.get("/health/live")
async def liveness():
    """Kubernetes liveness probe — just confirms process is running."""
    return {"status": "alive"}


@router.get("/health/ready")
async def readiness():
    """Kubernetes readiness probe — confirms ready to accept traffic."""
    db = await _check_database()
    if db.get("status") == "error":
        return JSONResponse(
            content={"status": "not_ready", "reason": "database unavailable"},
            status_code=503,
        )
    return {"status": "ready"}


# ── Helpers ────────────────────────────────────────────────


def _format_uptime(seconds: float) -> str:
    """Format seconds into human-readable uptime."""
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)

    parts = []
    if days > 0:
        parts.append(f"{days}d")
    if hours > 0:
        parts.append(f"{hours}h")
    parts.append(f"{minutes}m")

    return " ".join(parts)
