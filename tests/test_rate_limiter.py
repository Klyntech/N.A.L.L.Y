"""Regression tests for rate limiter correctness and bounded state."""

import importlib

web_app = importlib.import_module("nally.web.app")


def test_rate_limiter_enforces_burst_and_refills(monkeypatch):
    now = [100.0]
    monkeypatch.setattr(web_app.time, "time", lambda: now[0])
    monkeypatch.setattr(web_app, "RATE_LIMIT_ENABLED", True)
    limiter = web_app._RateLimiter(rpm=60, burst=2)

    assert limiter.allow("client-a")
    assert limiter.allow("client-a")
    assert not limiter.allow("client-a")

    now[0] = 102.0
    assert limiter.allow("client-a")


def test_rate_limiter_bounds_client_state(monkeypatch):
    monkeypatch.setattr(web_app.time, "time", lambda: 100.0)
    monkeypatch.setattr(web_app, "RATE_LIMIT_ENABLED", True)
    limiter = web_app._RateLimiter(rpm=60, burst=2)
    limiter._max_buckets = 2

    assert limiter.allow("client-a")
    assert limiter.allow("client-b")
    assert limiter.allow("client-c")
    assert len(limiter._buckets) == 2
    assert set(limiter._buckets) == {"client-b", "client-c"}
