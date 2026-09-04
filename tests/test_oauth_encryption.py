"""Regression tests: OAuth credential encryption fails closed (no plaintext)."""

from __future__ import annotations

import asyncio
import json
import sqlite3

import pytest

pytest.importorskip("cryptography")
from cryptography.fernet import Fernet

from nally.mcp.oauth import (
    CredentialEncryptionError,
    SQLiteTokenStorage,
    _decrypt_token,
    _encrypt_token,
    _reset_fernet_cache,
    load_oauth_state,
    save_oauth_state,
)


class _FakeToken:
    """Minimal token stand-in when mcp SDK is absent."""

    def __init__(self, access_token, token_type="bearer", expires_in=3600, refresh_token=None):
        self.access_token = access_token
        self.token_type = token_type
        self.expires_in = expires_in
        self.refresh_token = refresh_token

    def model_dump_json(self) -> str:
        return json.dumps(
            {
                "access_token": self.access_token,
                "token_type": self.token_type,
                "expires_in": self.expires_in,
                "refresh_token": self.refresh_token,
            }
        )

    @classmethod
    def model_validate_json(cls, data: str):
        d = json.loads(data)
        return cls(
            access_token=d["access_token"],
            token_type=d.get("token_type", "bearer"),
            expires_in=d.get("expires_in"),
            refresh_token=d.get("refresh_token"),
        )


@pytest.fixture(autouse=True)
def _clean_fernet_cache():
    _reset_fernet_cache()
    yield
    _reset_fernet_cache()


@pytest.fixture
def fernet_key(monkeypatch):
    key = Fernet.generate_key().decode()
    monkeypatch.setenv("NALLY_CRED_KEY", key)
    monkeypatch.delenv("NALLY_ALLOW_PLAINTEXT_TOKEN_MIGRATE", raising=False)
    _reset_fernet_cache()
    return key


@pytest.fixture
def no_encryption(monkeypatch):
    monkeypatch.setenv("NALLY_CRED_KEY", "")
    monkeypatch.delenv("NALLY_ALLOW_PLAINTEXT_TOKEN_MIGRATE", raising=False)
    _reset_fernet_cache()


def test_encrypt_decrypt_roundtrip(fernet_key):
    plain = '{"access_token":"secret-value","token_type":"bearer"}'
    enc = _encrypt_token(plain)
    assert enc != plain
    assert "secret-value" not in enc
    assert _decrypt_token(enc) == plain


def test_encrypt_fails_closed_without_key(no_encryption):
    with pytest.raises(CredentialEncryptionError):
        _encrypt_token('{"access_token":"x"}')


def test_decrypt_fails_closed_without_key(no_encryption):
    with pytest.raises(CredentialEncryptionError):
        _decrypt_token("gAAAAABnotrealciphertext")


def test_set_tokens_persists_encrypted(fernet_key, tmp_path, monkeypatch):
    import nally.mcp.oauth as oauth_mod

    monkeypatch.setattr(oauth_mod, "OAuthToken", _FakeToken)
    db = str(tmp_path / "t.db")
    storage = SQLiteTokenStorage(db, "notion")
    token = _FakeToken("access-secret", refresh_token="refresh-secret")
    asyncio.run(storage.set_tokens(token))

    conn = sqlite3.connect(db)
    row = conn.execute("SELECT tokens FROM mcp_oauth WHERE service=?", ("notion",)).fetchone()
    conn.close()
    assert row is not None
    raw = row[0]
    assert "access-secret" not in raw
    assert "refresh-secret" not in raw
    assert raw != token.model_dump_json()

    # get_tokens uses OAuthToken.model_validate_json — patch already applied
    loaded = asyncio.run(storage.get_tokens())
    assert loaded is not None
    assert loaded.access_token == "access-secret"
    assert loaded.refresh_token == "refresh-secret"


def test_set_tokens_fails_closed_no_partial_write(no_encryption, tmp_path, monkeypatch):
    import nally.mcp.oauth as oauth_mod

    monkeypatch.setattr(oauth_mod, "OAuthToken", _FakeToken)
    db = str(tmp_path / "t.db")
    storage = SQLiteTokenStorage(db, "gmail")
    token = _FakeToken("must-not-persist", refresh_token="must-not-persist-refresh")
    with pytest.raises(CredentialEncryptionError):
        asyncio.run(storage.set_tokens(token))

    conn = sqlite3.connect(db)
    row = conn.execute("SELECT tokens FROM mcp_oauth WHERE service=?", ("gmail",)).fetchone()
    conn.close()
    assert row is None or row[0] is None


def test_get_tokens_fails_closed_without_encryption(fernet_key, tmp_path, monkeypatch):
    import nally.mcp.oauth as oauth_mod

    monkeypatch.setattr(oauth_mod, "OAuthToken", _FakeToken)
    db = str(tmp_path / "t.db")
    storage = SQLiteTokenStorage(db, "github")
    token = _FakeToken("keep-secret", refresh_token="keep-refresh")
    asyncio.run(storage.set_tokens(token))

    monkeypatch.setenv("NALLY_CRED_KEY", "")
    _reset_fernet_cache()
    loaded = asyncio.run(storage.get_tokens())
    assert loaded is None


def test_plaintext_fallback_impossible(no_encryption):
    payload = '{"access_token":"plain"}'
    with pytest.raises(CredentialEncryptionError):
        _encrypt_token(payload)


def test_legacy_plaintext_not_auto_accepted(fernet_key):
    with pytest.raises(CredentialEncryptionError):
        _decrypt_token('{"access_token":"legacy","token_type":"bearer"}')


def test_legacy_plaintext_migrate_opt_in(fernet_key, monkeypatch):
    monkeypatch.setenv("NALLY_ALLOW_PLAINTEXT_TOKEN_MIGRATE", "1")
    _reset_fernet_cache()
    legacy = '{"access_token":"legacy","token_type":"bearer"}'
    assert _decrypt_token(legacy) == legacy


def test_oauth_state_verifier_encrypted(fernet_key, tmp_path):
    db = str(tmp_path / "s.db")
    save_oauth_state(
        db, "notion", "verifier-secret", "cid", "statexyz", "https://tok", "https://auth"
    )
    conn = sqlite3.connect(db)
    row = conn.execute(
        "SELECT code_verifier FROM mcp_oauth_state WHERE service=?", ("notion",)
    ).fetchone()
    conn.close()
    assert row is not None
    assert "verifier-secret" not in row[0]

    loaded = load_oauth_state(db, "notion")
    assert loaded is not None
    assert loaded["code_verifier"] == "verifier-secret"


def test_oauth_state_fails_closed_without_key(no_encryption, tmp_path):
    db = str(tmp_path / "s.db")
    with pytest.raises(CredentialEncryptionError):
        save_oauth_state(db, "notion", "verifier-secret", "cid", "st", "https://t", "https://a")


def test_refresh_path_set_tokens_fails_closed(no_encryption, tmp_path, monkeypatch):
    """Simulates gmail refresh calling set_tokens without encryption."""
    import nally.mcp.oauth as oauth_mod

    monkeypatch.setattr(oauth_mod, "OAuthToken", _FakeToken)
    storage = SQLiteTokenStorage(str(tmp_path / "r.db"), "gmail")
    new_token = _FakeToken("new-access", refresh_token="new-refresh")
    with pytest.raises(CredentialEncryptionError):
        asyncio.run(storage.set_tokens(new_token))
