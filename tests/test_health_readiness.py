"""Regression tests for health readiness gating."""

import asyncio
from unittest.mock import patch

from fastapi.responses import JSONResponse

from nally.web import health


def test_readiness_returns_503_until_core_tools_are_ready():
    with (
        patch("nally.web.health._check_database", return_value={"status": "ok"}),
        patch("nally.web.health._check_tools", return_value={"status": "not_ready", "missing": ["web_search"]}),
    ):
        response = asyncio.run(health.readiness())

    assert isinstance(response, JSONResponse)
    assert response.status_code == 503


def test_readiness_returns_200_when_database_and_tools_are_ready():
    with (
        patch("nally.web.health._check_database", return_value={"status": "ok"}),
        patch("nally.web.health._check_tools", return_value={"status": "ok", "count": 13}),
    ):
        response = asyncio.run(health.readiness())

    assert isinstance(response, dict)
    assert response["status"] == "ready"
