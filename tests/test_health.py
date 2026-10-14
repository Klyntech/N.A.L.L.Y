"""Regression tests for honest readiness reporting."""

import asyncio

from fastapi.responses import JSONResponse

from nally.web import health


def test_tools_are_not_ready_when_core_toolset_is_missing(monkeypatch):
    class EmptyRegistry:
        tools = {}

    monkeypatch.setattr("nally.tools.registry.registry", EmptyRegistry())
    result = health._check_tools()
    assert result["status"] == "not_ready"
    assert {"run_command", "read_file", "file_ops", "fetch"} <= set(result["missing"])


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
