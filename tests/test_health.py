"""Regression tests for honest readiness reporting."""

import asyncio
import importlib
import sys

from fastapi.responses import JSONResponse

from nally.web import health


def test_tools_are_not_ready_when_core_toolset_is_missing(monkeypatch):
    class EmptyRegistry:
        def __init__(self):
            self.tools = {}

        def get_all_tools(self):
            return []

    monkeypatch.setattr(importlib.import_module("nally.tools.registry"), "registry", EmptyRegistry())
    monkeypatch.setattr("nally.tools._loaded", False)
    result = health._check_tools()
    assert result["status"] == "not_ready"
    assert {"run_command", "read_file", "file_ops", "fetch"} <= set(result["missing"])


def test_tools_are_not_ready_when_web_search_is_missing(monkeypatch):
    class RegistryWithoutWebSearch:
        def get_all_tools(self):
            return [{"function": {"name": name}} for name in ("run_command", "read_file", "file_ops", "fetch")]

    monkeypatch.setattr(importlib.import_module("nally.tools.registry"), "registry", RegistryWithoutWebSearch())
    monkeypatch.setattr("nally.tools._loaded", True)
    result = health._check_tools()
    assert result["status"] == "not_ready"
    assert result["missing"] == ["web_search"]


def test_web_search_health_reports_available_provider_without_exposing_keys(monkeypatch):
    from nally.tools import websearch

    monkeypatch.setenv("TAVILY_API_KEY", "secret-tavily-key")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "")
    monkeypatch.setattr(websearch, "DDGS", None)
    result = health._check_web_search()
    assert result["status"] == "ok"
    assert "tavily" in result["providers"]
    assert "secret-tavily-key" not in str(result)
    assert result["connectivity"] == "not_probed"


def test_web_search_health_errors_when_no_provider_or_fallback_exists(monkeypatch):
    import builtins

    from nally.tools import websearch

    monkeypatch.setenv("TAVILY_API_KEY", "")
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "")
    monkeypatch.setattr(websearch, "DDGS", None)

    real_import = builtins.__import__

    def import_without_bs4(name, *args, **kwargs):
        if name == "bs4":
            raise ImportError("simulated missing parser")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", import_without_bs4)
    result = health._check_web_search()
    assert result["status"] == "error"
    assert result["providers"] == []


def test_readiness_returns_503_until_tools_are_registered(monkeypatch):
    async def database_ok():
        return {"status": "ok", "engine": "sqlite"}

    monkeypatch.setattr(health, "_check_database", database_ok)
    monkeypatch.setattr(health, "_check_tools", lambda: {"status": "not_ready", "missing": ["fetch"]})
    response = asyncio.run(health.readiness())
    assert isinstance(response, JSONResponse)
    assert response.status_code == 503


def test_readiness_returns_503_when_web_search_has_no_provider(monkeypatch):
    async def database_ok():
        return {"status": "ok", "engine": "sqlite"}

    monkeypatch.setattr(health, "_check_database", database_ok)
    monkeypatch.setattr(health, "_check_tools", lambda: {"status": "ok", "count": 8})
    monkeypatch.setattr(health, "_check_web_search", lambda: {"status": "error", "providers": []})

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
