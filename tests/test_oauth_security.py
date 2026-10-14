"""Regression tests for OAuth credential storage security."""

import pytest

from nally.mcp import oauth


def test_production_refuses_plaintext_oauth_storage_without_key(monkeypatch):
    monkeypatch.setattr(oauth, "_FERNET", None)
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.delenv("NALLY_CRED_KEY", raising=False)

    with pytest.raises(RuntimeError, match="NALLY_CRED_KEY"):
        oauth._encrypt_token('{"access_token":"not-a-real-secret"}')


def test_production_rejects_invalid_credential_key(monkeypatch):
    monkeypatch.setattr(oauth, "_FERNET", None)
    monkeypatch.setenv("NALLY_ENV", "production")
    monkeypatch.setenv("NALLY_CRED_KEY", "not-a-valid-fernet-key")

    with pytest.raises(RuntimeError, match="NALLY_CRED_KEY is invalid"):
        oauth._encrypt_token('{"access_token":"not-a-real-secret"}')



def test_production_rejects_legacy_plaintext_token(monkeypatch):
    from cryptography.fernet import Fernet

    monkeypatch.setattr(oauth, "_FERNET", None)
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("NALLY_CRED_KEY", Fernet.generate_key().decode())

    with pytest.raises(RuntimeError, match="not encrypted"):
        oauth._decrypt_token('{"access_token":"legacy-plaintext"}')



def test_oauth_callback_state_must_match_pending_state(monkeypatch, tmp_path):
    monkeypatch.setitem(oauth._pending_pkce, "notion", {"state": "expected-state"})

    assert oauth.validate_oauth_state("notion", "expected-state", str(tmp_path / "oauth.db"))
    assert not oauth.validate_oauth_state("notion", "attacker-state", str(tmp_path / "oauth.db"))
    assert not oauth.validate_oauth_state("notion", "", str(tmp_path / "oauth.db"))



def test_local_development_never_writes_plaintext_oauth_tokens(monkeypatch):
    monkeypatch.setattr(oauth, "_FERNET", None)
    monkeypatch.delenv("RENDER", raising=False)
    monkeypatch.delenv("NALLY_ENV", raising=False)
    monkeypatch.delenv("NALLY_CRED_KEY", raising=False)

    with pytest.raises(RuntimeError, match="required to store OAuth tokens"):
        oauth._encrypt_token('{"access_token":"not-a-real-secret"}')
