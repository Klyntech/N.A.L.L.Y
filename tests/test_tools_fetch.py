"""Tests for nally.tools.fetch — FetchTool with retry and SSL config."""

import os
import socket
from unittest.mock import MagicMock, patch

import pytest

from nally.tools.fetch import VERIFY_SSL, FetchTool, _fetch_url, _validate_public_url


@pytest.fixture
def fetch_tool():
    return FetchTool()


class TestFetchTool:
    def test_invalid_scheme(self, fetch_tool):
        result = fetch_tool.execute(url="ftp://example.com")
        assert "Error" in result
        assert "http/https" in result

    def test_missing_url(self):
        from nally.tools.fetch import _fetch_url

        result = _fetch_url("not-a-url")
        assert "Error" in result

    def test_empty_url(self, fetch_tool):
        # Empty string has no scheme
        result = fetch_tool.execute(url="")
        assert "Error" in result


class TestVerifySSL:
    def test_default_is_true(self):
        """SSL verification is enabled by default."""
        assert VERIFY_SSL is True

    def test_env_var_true(self):
        """NALLY_VERIFY_SSL=true enables verification."""
        with patch.dict(os.environ, {"NALLY_VERIFY_SSL": "true"}):
            # Re-import to pick up env change
            import importlib

            import nally.tools.fetch as fetch_mod

            importlib.reload(fetch_mod)
            assert fetch_mod.VERIFY_SSL is True
            # Restore default
            importlib.reload(fetch_mod)

    def test_env_var_1(self):
        """NALLY_VERIFY_SSL=1 also enables verification."""
        with patch.dict(os.environ, {"NALLY_VERIFY_SSL": "1"}):
            import importlib

            import nally.tools.fetch as fetch_mod

            importlib.reload(fetch_mod)
            assert fetch_mod.VERIFY_SSL is True
            importlib.reload(fetch_mod)


class TestFetchUrlRetry:
    def test_retry_on_500(self):
        """500 errors should be retried then fail."""
        with patch("nally.tools.fetch._validate_public_url", return_value=None), patch(
            "nally.tools.fetch.httpx.Client"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)

            import httpx

            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "500", request=MagicMock(), response=MagicMock(status_code=500)
            )
            mock_client.get.return_value = mock_resp

            result = _fetch_url("https://example.com")
            assert "Error" in result

    def test_retry_on_timeout(self):
        """Timeout errors should be retried."""
        import httpx

        with patch("nally.tools.fetch._validate_public_url", return_value=None), patch(
            "nally.tools.fetch.httpx.Client"
        ) as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.get.side_effect = httpx.TimeoutException("timed out")

            result = _fetch_url("https://example.com")
            assert "Error" in result
            assert "timed out" in result.lower()



class TestFetchSSRFProtection:
    def test_blocks_loopback_and_private_literal_addresses(self):
        assert _validate_public_url("http://127.0.0.1") is not None
        assert _validate_public_url("http://192.168.1.10") is not None
        assert _validate_public_url("http://[::1]") is not None

    def test_blocks_hostname_resolving_to_private_address(self):
        private_record = (
            socket.AF_INET,
            socket.SOCK_STREAM,
            6,
            "",
            ("10.0.0.5", 80),
        )
        with patch("nally.tools.fetch.socket.getaddrinfo", return_value=[private_record]):
            assert _validate_public_url("http://internal.example") is not None

    def test_rejects_credentials_in_url(self):
        assert _validate_public_url("https://user:pass@example.com") is not None
