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
