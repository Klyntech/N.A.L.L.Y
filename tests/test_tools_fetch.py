"""Tests for nally.tools.fetch — FetchTool with retry and SSL config."""

import os
import pytest
from unittest.mock import patch, MagicMock
from nally.tools.fetch import FetchTool, _fetch_url, VERIFY_SSL


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
    def test_default_is_false(self):
        """SSL verification is disabled by default."""
        assert VERIFY_SSL is False

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
        with patch("nally.tools.fetch.httpx.Client") as mock_client_cls:
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
        with patch("nally.tools.fetch.httpx.Client") as mock_client_cls:
            mock_client = MagicMock()
            mock_client_cls.return_value.__enter__ = MagicMock(return_value=mock_client)
            mock_client_cls.return_value.__exit__ = MagicMock(return_value=False)
            mock_client.get.side_effect = httpx.TimeoutException("timed out")

            result = _fetch_url("https://example.com")
            assert "Error" in result
            assert "timed out" in result.lower()
