"""Regression tests for honest readiness reporting."""

import asyncio
import sys

from fastapi.responses import JSONResponse

from nally.web import health


def test_tools_are_not_ready_when_core_toolset_is_missing(monkeypatch):
    class EmptyRegistry:
        def __init__(self):
            self.tools = {}

        def get_all_tools(self):
            return []

    monkeypatch.setattr("nally.tools.registry.registry", EmptyRegistry())
    monkeypatch.setattr("nally.tools._loaded", False)
    result = health._check_tools()
    assert result["status"] == "not_ready"
    assert {"run_command", "read_file", "file_ops", "fetch"} <= set(result["missing"])


def test_tools_are_not_ready_when_web_search_is_missing(monkeypatch):
    class RegistryWithoutWebSearch:
        def get_all_tools(self):
            return [
                {"function": {"name": name}}
                for name in ("run_command", "read_file", "file_ops", "fetch")
            ]

    monkeypatch.setattr("nally.tools.registry.registry", RegistryWithoutWebSearch())
    monkeypatch.setattr("nally.tools._loaded", True)
    result = health._check_tools()
    assert result["status"] == "not_ready"
    assert result["missing"] == ["web_search"]


def test_readiness_returns_503_until_tools_are_registered(monkeypatch):
    async def database_ok():
        return {"status": "ok", "engine": "sqlite"}

    monkeypatch.setattr(health, "_check_database", database_ok)
    monkeypatch.setattr(health, "_check_tools", lambda: {"status": "not_ready", "missing": ["fetch"]})
    response = asyncio.run(health.readiness())
    assert isinstance(response, JSONResponse)
    assert response.status_code == 503


def test_readiness_returns_503_when_database_is_unavailable(monkeypatch):
    async def database_error():
        return {"status": "error"}

    monkeypatch.setattr(health, "_check_database", database_error)
    monkeypatch.setattr(health, "_check_tools", lambda: {"status": "ok", "count": 7})
    response = asyncio.run(health.readiness())
    assert isinstance(response, JSONResponse)
    assert response.status_code == 503


def test_health_never_returns_libsql_connection_token(monkeypatch):
    monkeypatch.setattr(health, "memory_backend", lambda: "turso")
    monkeypatch.setattr(health, "TURSO_URL", "libsql://db.example")
    monkeypatch.setattr(health, "TURSO_TOKEN", "secret-value")
    monkeypatch.setitem(sys.modules, "libsql_experimental", None)
    result = asyncio.run(health._check_database())
    assert result["engine"] == "turso"
    assert "secret-value" not in str(result)


def test_redis_health_does_not_expose_connection_secrets(monkeypatch):
    class FailingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            raise RuntimeError("connection failed for https://layerbase.example/secret-value")

    monkeypatch.setenv("REDIS_URL", "https://layerbase.example")
    monkeypatch.setenv("REDIS_TOKEN", "secret-value")
    monkeypatch.setattr("httpx.AsyncClient", lambda: FailingClient())
    result = asyncio.run(health._check_redis())

    assert result["status"] == "error"
    assert "secret-value" not in str(result)
