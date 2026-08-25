"""Tests for nally.tools._retry — shared retry utility."""

import time
import pytest
from nally.tools._retry import retry_transient, _is_transient, TRANSIENT_HINTS


class TestIsTransient:
    def test_timeout_is_transient(self):
        assert _is_transient(Exception("Connection timed out")) is True

    def test_rate_limit_is_transient(self):
        assert _is_transient(Exception("429 Too Many Requests")) is True

    def test_503_is_transient(self):
        assert _is_transient(Exception("503 Service Unavailable")) is True

    def test_file_not_found_is_not_transient(self):
        assert _is_transient(Exception("File not found: /tmp/foo.txt")) is False

    def test_permission_denied_is_not_transient(self):
        assert _is_transient(Exception("Permission denied")) is False

    def test_empty_string_is_not_transient(self):
        assert _is_transient(Exception("")) is False

    def test_case_insensitive(self):
        assert _is_transient(Exception("TIMEOUT exceeded")) is True
        assert _is_transient(Exception("Rate Limit hit")) is True


class TestRetryTransient:
    def test_success_on_first_attempt(self):
        call_count = [0]
        def func():
            call_count[0] += 1
            return "ok"

        result, exc = retry_transient(func, max_attempts=3)
        assert result == "ok"
        assert exc is None
        assert call_count[0] == 1

    def test_retries_on_transient_error(self):
        call_count = [0]
        def func():
            call_count[0] += 1
            if call_count[0] < 3:
                raise Exception("Connection timed out")
            return "recovered"

        result, exc = retry_transient(func, max_attempts=3, backoff_base=0.01)
        assert result == "recovered"
        assert exc is None
        assert call_count[0] == 3

    def test_fails_after_max_attempts(self):
        def func():
            raise Exception("503 Service Unavailable")

        result, exc = retry_transient(func, max_attempts=2, backoff_base=0.01)
        assert result is None
        assert exc is not None
        assert "503" in str(exc)

    def test_no_retry_on_permanent_error(self):
        call_count = [0]
        def func():
            call_count[0] += 1
            raise Exception("File not found")

        result, exc = retry_transient(func, max_attempts=3, backoff_base=0.01)
        assert result is None
        assert call_count[0] == 1  # No retry

    def test_backoff_timing(self):
        call_count = [0]
        def func():
            call_count[0] += 1
            if call_count[0] < 3:
                raise Exception("timeout")
            return "ok"

        start = time.monotonic()
        result, exc = retry_transient(func, max_attempts=3, backoff_base=0.05, backoff_max=0.5)
        elapsed = time.monotonic() - start

        assert result == "ok"
        # Should have waited ~0.05 + ~0.10 = 0.15s minimum
        assert elapsed >= 0.10

    def test_max_attempts_1_no_retry(self):
        call_count = [0]
        def func():
            call_count[0] += 1
            raise Exception("timeout")

        result, exc = retry_transient(func, max_attempts=1, backoff_base=0.01)
        assert result is None
        assert call_count[0] == 1

    def test_result_is_none_not_string(self):
        """Ensure None results are handled (not confused with falsy strings)."""
        def func():
            return None

        result, exc = retry_transient(func, max_attempts=1)
        assert result is None
        assert exc is None
