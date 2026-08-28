"""Regression tests for privileged internal API trust boundaries."""

import importlib
import time
import uuid

from fastapi.testclient import TestClient

web_app = importlib.import_module("nally.web.app")


INTERNAL_TOKEN = "test-internal-token-abcdefghijklmnopqrstuvwxyz"
ACCESS_TOKEN = "test-access-token-abcdefghijklmnopqrstuvwxyz"


def _internal_headers(nonce=None, timestamp=None):
    return {
        "X-NALLY-INTERNAL-TOKEN": INTERNAL_TOKEN,
        "X-NALLY-INTERNAL-TIMESTAMP": str(int(time.time()) if timestamp is None else timestamp),
        "X-NALLY-INTERNAL-NONCE": nonce or uuid.uuid4().hex,
    }


def test_telegram_message_rejects_missing_internal_auth(monkeypatch):
    monkeypatch.setenv("NALLY_INTERNAL_TOKEN", INTERNAL_TOKEN)
    client = TestClient(web_app.app)
    response = client.post(
        "/api/telegram/message",
        json={"session_id": "user:1", "route_key": "telegram:1", "text": "hello", "chat_id": 1},
    )
    assert response.status_code == 401


def test_telegram_approve_rejects_missing_internal_auth(monkeypatch):
    monkeypatch.setenv("NALLY_INTERNAL_TOKEN", INTERNAL_TOKEN)
    client = TestClient(web_app.app)
    response = client.post("/api/telegram/approve", json={"tc_id": "tc1", "approved": True})
    assert response.status_code == 401


def test_bridges_requires_bearer_auth(monkeypatch):
    monkeypatch.setenv("NALLY_ACCESS_TOKEN", ACCESS_TOKEN)
    client = TestClient(web_app.app)
    response = client.get("/api/bridges")
    assert response.status_code == 401


def test_internal_auth_rejects_replay(monkeypatch):
    monkeypatch.setenv("NALLY_INTERNAL_TOKEN", INTERNAL_TOKEN)
    web_app._internal_nonces.clear()
    client = TestClient(web_app.app)
    headers = _internal_headers(nonce="replay-test-nonce")
    payload = {"tc_id": "tc1", "approved": False}

    first = client.post("/api/telegram/approve", json=payload, headers=headers)
    second = client.post("/api/telegram/approve", json=payload, headers=headers)

    assert first.status_code == 200
    assert second.status_code == 401


def test_internal_auth_rejects_expired_timestamp(monkeypatch):
    monkeypatch.setenv("NALLY_INTERNAL_TOKEN", INTERNAL_TOKEN)
    client = TestClient(web_app.app)
    headers = _internal_headers(timestamp=int(time.time()) - 301)
    response = client.post(
        "/api/telegram/approve",
        json={"tc_id": "tc1", "approved": False},
        headers=headers,
    )
    assert response.status_code == 401


def test_telegram_payload_rejects_unknown_fields(monkeypatch):
    monkeypatch.setenv("NALLY_INTERNAL_TOKEN", INTERNAL_TOKEN)
    client = TestClient(web_app.app)
    response = client.post(
        "/api/telegram/approve",
        json={"tc_id": "tc1", "approved": False, "session_id": "attacker"},
        headers=_internal_headers(),
    )
    assert response.status_code == 422


def test_validator_requires_internal_token_when_telegram_enabled(monkeypatch):
    from nally.core.validator import validate_config

    monkeypatch.setenv("NALLY_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:telegram-token")
    monkeypatch.setenv("TELEGRAM_MODE", "polling")
    monkeypatch.delenv("NALLY_INTERNAL_TOKEN", raising=False)
    errors = validate_config(strict=False)
    assert any(key == "NALLY_INTERNAL_TOKEN" and level == "error" for level, key, _ in errors)


def test_validator_allows_telegram_off_without_internal_token(monkeypatch):
    from nally.core.validator import validate_config

    monkeypatch.setenv("NALLY_ACCESS_TOKEN", ACCESS_TOKEN)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123456:telegram-token")
    monkeypatch.setenv("TELEGRAM_MODE", "off")
    monkeypatch.delenv("NALLY_INTERNAL_TOKEN", raising=False)
    errors = validate_config(strict=False)
    assert not any(key == "NALLY_INTERNAL_TOKEN" and level == "error" for level, key, _ in errors)

