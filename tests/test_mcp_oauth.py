"""Tests for OAuth manager: token storage, callback flow, provider creation."""
import asyncio
import os
import sqlite3
import tempfile
import pytest
from unittest.mock import patch, MagicMock, AsyncMock

from nally.mcp.oauth import (
    SQLiteTokenStorage,
    complete_callback,
    create_oauth_provider,
    get_auth_url,
    revoke_service,
    get_existing_tokens,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


@pytest.fixture
def tmp_db():
    """Create a temporary SQLite database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


@pytest.fixture
def storage(tmp_db):
    return SQLiteTokenStorage(tmp_db, "test_service")


# ── Token Storage ──────────────────────────────────────

def test_storage_creates_table(storage):
    """Storage creates mcp_oauth table on init."""
    conn = sqlite3.connect(storage.db_path)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    conn.close()
    assert any("mcp_oauth" in t[0] for t in tables)


def test_storage_get_tokens_empty(storage):
    """get_tokens returns None when no tokens stored."""
    result = asyncio.run(storage.get_tokens())
    assert result is None


def test_storage_set_get_tokens(storage):
    """set_tokens stores and get_tokens retrieves."""
    token = OAuthToken(
        access_token="test_token_123",
        token_type="bearer",
        expires_in=3600,
    )
    asyncio.run(storage.set_tokens(token))
    retrieved = asyncio.run(storage.get_tokens())
    assert retrieved is not None
    assert retrieved.access_token == "test_token_123"


def test_storage_set_get_client_info(storage):
    """set_client_info stores and get_client_info retrieves."""
    info = OAuthClientInformationFull(
        client_id="client_abc",
        client_secret="secret_xyz",
        redirect_uris=["http://localhost:5000/api/oauth/callback"],
        client_name="Nally (test)",
    )
    asyncio.run(storage.set_client_info(info))
    retrieved = asyncio.run(storage.get_client_info())
    assert retrieved is not None
    assert retrieved.client_id == "client_abc"


def test_storage_service_isolation(tmp_db):
    """Different services have separate token storage."""
    s1 = SQLiteTokenStorage(tmp_db, "service_a")
    s2 = SQLiteTokenStorage(tmp_db, "service_b")
    token = OAuthToken(access_token="token_a", token_type="bearer")
    asyncio.run(s1.set_tokens(token))
    assert asyncio.run(s1.get_tokens()) is not None
    assert asyncio.run(s2.get_tokens()) is None


# ── Callback Flow ──────────────────────────────────────

def test_complete_callback_no_pending():
    """complete_callback returns False when no flow pending."""
    result = complete_callback("nonexistent_service", "code_123")
    assert result is False


def test_get_auth_url_no_pending():
    """get_auth_url returns None when no flow pending."""
    result = get_auth_url("nonexistent_service")
    assert result is None


# ── Revoke ─────────────────────────────────────────────

def test_revoke_service(tmp_db):
    """revoke_service removes tokens from storage."""
    storage = SQLiteTokenStorage(tmp_db, "to_revoke")
    token = OAuthToken(access_token="temp", token_type="bearer")
    asyncio.run(storage.set_tokens(token))
    assert revoke_service("to_revoke", tmp_db) is True
    assert asyncio.run(storage.get_tokens()) is None


def test_revoke_nonexistent(tmp_db):
    """revoke_service returns False for nonexistent service."""
    # Ensure table exists first
    from nally.mcp.oauth import SQLiteTokenStorage
    SQLiteTokenStorage(tmp_db, "setup")
    assert revoke_service("ghost", tmp_db) is False


# ── Existing Tokens ────────────────────────────────────

def test_get_existing_tokens_none(tmp_db):
    """get_existing_tokens returns None when no tokens."""
    result = asyncio.run(get_existing_tokens("nope", tmp_db))
    assert result is None


def test_get_existing_tokens_present(tmp_db):
    """get_existing_tokens returns token when present."""
    storage = SQLiteTokenStorage(tmp_db, "has_tokens")
    token = OAuthToken(access_token="exists", token_type="bearer")
    asyncio.run(storage.set_tokens(token))
    result = asyncio.run(get_existing_tokens("has_tokens", tmp_db))
    assert result is not None
    assert result.access_token == "exists"


# ── Provider Creation ──────────────────────────────────

def test_create_oauth_provider(tmp_db):
    """create_oauth_provider returns an OAuthClientProvider."""
    from mcp.client.auth.oauth2 import OAuthClientProvider

    provider = asyncio.run(create_oauth_provider(
        service="test_svc",
        server_url="https://example.com/mcp",
        db_path=tmp_db,
    ))
    assert isinstance(provider, OAuthClientProvider)
