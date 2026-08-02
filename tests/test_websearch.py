"""Tests for web search tool: usage tracking, fallback logic, result formatting."""

import os
import sqlite3
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from nally.tools.websearch import (
    PARALLEL_MONTHLY_LIMIT,
    WebSearch,
    _ensure_usage_table,
    _get_monthly_count,
    _increment_monthly_count,
    _search_duckduckgo,
    _search_parallel,
)


@pytest.fixture
def tmp_db():
    """Create a temporary SQLite database."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    os.unlink(path)


# ── Usage Tracking ───────────────────────────────────────


def test_ensure_usage_table_creates_table(tmp_db):
    """_ensure_usage_table creates web_search_usage table."""
    _ensure_usage_table(tmp_db)
    conn = sqlite3.connect(tmp_db)
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    conn.close()
    assert any("web_search_usage" in t[0] for t in tables)


def test_get_monthly_count_empty(tmp_db):
    """_get_monthly_count returns 0 when no rows exist."""
    _ensure_usage_table(tmp_db)
    count = _get_monthly_count(tmp_db, "parallel")
    assert count == 0


def test_increment_monthly_count(tmp_db):
    """_increment_monthly_count increments the count."""
    _ensure_usage_table(tmp_db)
    _increment_monthly_count(tmp_db, "parallel")
    _increment_monthly_count(tmp_db, "parallel")
    count = _get_monthly_count(tmp_db, "parallel")
    assert count == 2


def test_increment_monthly_count_different_providers(tmp_db):
    """Different providers have separate counts."""
    _ensure_usage_table(tmp_db)
    _increment_monthly_count(tmp_db, "parallel")
    _increment_monthly_count(tmp_db, "parallel")
    _increment_monthly_count(tmp_db, "duckduckgo")
    assert _get_monthly_count(tmp_db, "parallel") == 2
    assert _get_monthly_count(tmp_db, "duckduckgo") == 1


# ── Parallel.ai Search ──────────────────────────────────


def test_search_parallel_no_api_key(tmp_db):
    """_search_parallel returns None when no API key set."""
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("PARALLEL_API_KEY", None)
        result = _search_parallel("test query")
        assert result is None


def test_search_parallel_quota_exceeded(tmp_db):
    """_search_parallel returns None when monthly quota exceeded."""
    _ensure_usage_table(tmp_db)
    # Set count directly to limit
    from datetime import datetime

    month = datetime.now().strftime("%Y-%m")
    conn = sqlite3.connect(tmp_db)
    conn.execute(
        "INSERT INTO web_search_usage (month, provider, count) VALUES (?, ?, ?)",
        (month, "parallel", PARALLEL_MONTHLY_LIMIT),
    )
    conn.commit()
    conn.close()

    with (
        patch("nally.tools.websearch._get_db_path", return_value=tmp_db),
        patch.dict(os.environ, {"PARALLEL_API_KEY": "test_key"}),
    ):
        result = _search_parallel("test query")
        assert result is None


def test_search_parallel_success(tmp_db):
    """_search_parallel returns formatted results on success."""
    _ensure_usage_table(tmp_db)

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "results": [
            {
                "title": "Test Result",
                "url": "https://example.com",
                "excerpts": ["This is a test snippet about the topic."],
            }
        ]
    }

    with (
        patch("nally.tools.websearch._get_db_path", return_value=tmp_db),
        patch.dict(os.environ, {"PARALLEL_API_KEY": "test_key"}),
        patch("nally.tools.websearch.httpx.post", return_value=mock_resp),
    ):
        result = _search_parallel("test query")

    assert result is not None
    assert "Test Result" in result
    assert "https://example.com" in result
    assert "test snippet" in result


def test_search_parallel_api_error(tmp_db):
    """_search_parallel returns None on API error."""
    _ensure_usage_table(tmp_db)

    mock_resp = MagicMock()
    mock_resp.status_code = 500
    mock_resp.text = "Internal Server Error"

    with (
        patch("nally.tools.websearch._get_db_path", return_value=tmp_db),
        patch.dict(os.environ, {"PARALLEL_API_KEY": "test_key"}),
        patch("nally.tools.websearch.httpx.post", return_value=mock_resp),
    ):
        result = _search_parallel("test query")
        assert result is None


# ── DuckDuckGo Fallback ─────────────────────────────────


def test_search_duckduckgo_returns_results():
    """_search_duckduckgo returns formatted results."""
    mock_results = [
        {"title": "DDG Result", "href": "https://ddg.com", "body": "DuckDuckGo snippet"},
    ]

    with patch("nally.tools.websearch.DDGS") as MockDDGS:
        instance = MagicMock()
        instance.text.return_value = mock_results
        instance.__enter__ = MagicMock(return_value=instance)
        instance.__exit__ = MagicMock(return_value=False)
        MockDDGS.return_value = instance

        result = _search_duckduckgo("test query")
        assert "DDG Result" in result
        assert "https://ddg.com" in result


def test_search_duckduckgo_import_error():
    """_search_duckduckgo falls back to curl when duckduckgo-search not installed."""
    with patch("nally.tools.websearch.DDGS", None):
        with patch("nally.tools.websearch._search_fallback", return_value="fallback result") as mock_fallback:
            result = _search_duckduckgo("test query")
            assert result == "fallback result"
            mock_fallback.assert_called_once_with("test query", 3)


# ── Tool Schema ─────────────────────────────────────────


def test_web_search_tool_schema():
    """WebSearch tool has correct schema."""
    tool = WebSearch()
    assert tool.name == "web_search"
    assert "query" in tool.parameters
    assert "num_results" in tool.parameters
    assert tool.parameters["query"]["required"] is True
    assert tool.permission == "safe"


def test_web_search_num_results_clamped():
    """WebSearch clamps num_results to 1-5."""
    tool = WebSearch()
    with patch("nally.tools.websearch._search_parallel", return_value="result") as mock_search:
        tool.execute(query="test", num_results=10)
        # Should be called with clamped value
        call_args = mock_search.call_args
        assert call_args[0][1] == 5  # clamped to max

        tool.execute(query="test", num_results=0)
        call_args = mock_search.call_args
        assert call_args[0][1] == 1  # clamped to min
