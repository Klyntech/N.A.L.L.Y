"""Tests for OAuth manager: token storage, callback flow, provider creation, PKCE, Notion/Google flows."""
import asyncio
import base64
import hashlib
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
    generate_pkce,
    _pending_pkce,
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


# ── PKCE ─────────────────────────────────────────────────

def test_generate_pkce_returns_two_strings():
    """generate_pkce returns (code_verifier, code_challenge) tuple."""
    verifier, challenge = generate_pkce()
    assert isinstance(verifier, str)
    assert isinstance(challenge, str)
    assert len(verifier) > 0
    assert len(challenge) > 0


def test_generate_pkce_challenge_is_s256():
    """code_challenge is BASE64URL(SHA-256(code_verifier))."""
    verifier, challenge = generate_pkce()
    expected = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    assert challenge == expected


def test_generate_pkce_unique():
    """Each call produces different verifiers."""
    v1, c1 = generate_pkce()
    v2, c2 = generate_pkce()
    assert v1 != v2
    assert c1 != c2


# ── Notion OAuth ─────────────────────────────────────────

def test_start_notion_oauth_builds_auth_url(tmp_db):
    """start_notion_oauth performs DCR and returns a Notion authorize URL."""
    from nally.mcp.oauth import start_notion_oauth, NOTION_AUTH_ENDPOINT

    mock_dcr = {"client_id": "test_client_123", "client_id_issued_at": 12345}
    mock_response = MagicMock()
    mock_response.json.return_value = mock_dcr
    mock_response.raise_for_status = MagicMock()

    with patch("nally.mcp.oauth.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.post = AsyncMock(return_value=mock_response)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        auth_url = asyncio.run(start_notion_oauth(tmp_db))

    assert auth_url.startswith(NOTION_AUTH_ENDPOINT)
    assert "client_id=test_client_123" in auth_url
    assert "code_challenge=" in auth_url
    assert "code_challenge_method=S256" in auth_url
    assert "state=" in auth_url
    # Verify PKCE state was stored
    assert "notion" in _pending_pkce
    assert _pending_pkce["notion"]["client_id"] == "test_client_123"


def test_exchange_notion_code_success(tmp_db):
    """exchange_notion_code exchanges code and stores token."""
    from nally.mcp.oauth import exchange_notion_code

    # Set up pending state
    _pending_pkce["notion"] = {
        "code_verifier": "test_verifier",
        "client_id": "test_client",
        "state": "test_state",
    }

    mock_token_resp = MagicMock()
    mock_token_resp.status_code = 200
    mock_token_resp.json.return_value = {
        "access_token": "ntn_test_token",
        "token_type": "bearer",
        "expires_in": 28800,
        "refresh_token": "ntn_refresh",
    }

    with patch("nally.mcp.oauth.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.post = AsyncMock(return_value=mock_token_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        result = asyncio.run(exchange_notion_code("auth_code_123", tmp_db))

    assert result is True
    assert "notion" not in _pending_pkce
    # Verify token was stored
    storage = SQLiteTokenStorage(tmp_db, "notion")
    token = asyncio.run(storage.get_tokens())
    assert token is not None
    assert token.access_token == "ntn_test_token"


def test_exchange_notion_code_no_pending():
    """exchange_notion_code returns False when no pending state."""
    from nally.mcp.oauth import exchange_notion_code
    # Ensure no pending state for notion
    _pending_pkce.pop("notion", None)
    result = asyncio.run(exchange_notion_code("code", "/tmp/nonexistent.db"))
    assert result is False


# ── Google OAuth ─────────────────────────────────────────

def test_get_google_credentials_missing():
    """_get_google_credentials returns None when env vars missing."""
    from nally.mcp.oauth import _get_google_credentials
    with patch.dict(os.environ, {}, clear=True):
        # Remove google vars if present
        os.environ.pop("GOOGLE_CLIENT_ID", None)
        os.environ.pop("GOOGLE_CLIENT_SECRET", None)
        result = _get_google_credentials()
        assert result is None


def test_get_google_credentials_present():
    """_get_google_credentials returns (client_id, client_secret) when set."""
    from nally.mcp.oauth import _get_google_credentials
    env = {"GOOGLE_CLIENT_ID": "my_id", "GOOGLE_CLIENT_SECRET": "my_secret"}
    with patch.dict(os.environ, env, clear=False):
        result = _get_google_credentials()
        assert result == ("my_id", "my_secret")


def test_start_google_oauth_builds_auth_url(tmp_db):
    """start_google_oauth returns a Google authorize URL."""
    from nally.mcp.oauth import start_google_oauth, GOOGLE_AUTH_ENDPOINT

    env = {"GOOGLE_CLIENT_ID": "g_id", "GOOGLE_CLIENT_SECRET": "g_secret"}
    with patch.dict(os.environ, env, clear=False):
        auth_url = asyncio.run(start_google_oauth("gmail", tmp_db))

    assert auth_url.startswith(GOOGLE_AUTH_ENDPOINT)
    assert "client_id=g_id" in auth_url
    assert "code_challenge=" in auth_url
    assert "access_type=offline" in auth_url
    assert "prompt=consent" in auth_url
    assert "google" in _pending_pkce
    assert _pending_pkce["google"]["service"] == "gmail"


def test_start_google_oauth_raises_without_creds(tmp_db):
    """start_google_oauth raises ValueError when credentials missing."""
    from nally.mcp.oauth import start_google_oauth
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("GOOGLE_CLIENT_ID", None)
        os.environ.pop("GOOGLE_CLIENT_SECRET", None)
        with pytest.raises(ValueError, match="GOOGLE_CLIENT_ID"):
            asyncio.run(start_google_oauth("gmail", tmp_db))


def test_exchange_google_code_success(tmp_db):
    """exchange_google_code exchanges code and stores token for all Google services."""
    from nally.mcp.oauth import exchange_google_code, GOOGLE_SERVICES

    _pending_pkce["google"] = {
        "code_verifier": "g_verifier",
        "client_id": "g_client",
        "state": "g_state",
        "service": "gmail",
    }

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "access_token": "google_token_abc",
        "token_type": "bearer",
        "expires_in": 3600,
        "refresh_token": "google_refresh",
    }

    env = {"GOOGLE_CLIENT_ID": "g_client", "GOOGLE_CLIENT_SECRET": "g_secret"}
    with patch.dict(os.environ, env, clear=False), \
         patch("nally.mcp.oauth.httpx.AsyncClient") as MockClient:
        instance = AsyncMock()
        instance.post = AsyncMock(return_value=mock_resp)
        instance.__aenter__ = AsyncMock(return_value=instance)
        instance.__aexit__ = AsyncMock(return_value=False)
        MockClient.return_value = instance

        result = asyncio.run(exchange_google_code("g_code", tmp_db))

    assert result is True
    assert "google" not in _pending_pkce
    # Verify token stored for all Google services
    for svc in GOOGLE_SERVICES:
        storage = SQLiteTokenStorage(tmp_db, svc)
        token = asyncio.run(storage.get_tokens())
        assert token is not None
        assert token.access_token == "google_token_abc"
