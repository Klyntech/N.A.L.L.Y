"""Tests for Tavily and DuckDuckGo web search provider fallback."""

import os
from unittest.mock import MagicMock, patch

from nally.tools.websearch import WebSearch, _search_duckduckgo, _search_tavily


def test_tavily_no_api_key_uses_fallback():
    with patch.dict(os.environ, {}, clear=True):
        assert _search_tavily("test query") is None


def test_tavily_success_formats_results():
    response = MagicMock()
    response.json.return_value = {
        "results": [
            {
                "title": "Test Result",
                "url": "https://example.com",
                "content": "A useful test snippet.",
            }
        ]
    }
    response.raise_for_status.return_value = None

    with (
        patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}),
        patch("nally.tools.websearch.httpx.post", return_value=response) as post,
    ):
        result = _search_tavily("test query", 2)

    assert "Test Result" in result
    assert "https://example.com" in result
    assert "useful test snippet" in result
    assert post.call_args.kwargs["json"]["api_key"] == "test-key"
    assert post.call_args.args[0] == "https://api.tavily.com/search"


def test_tavily_http_error_returns_none():
    import httpx

    with (
        patch.dict(os.environ, {"TAVILY_API_KEY": "test-key"}),
        patch(
            "nally.tools.websearch.httpx.post",
            side_effect=httpx.ConnectError("connection failed"),
        ),
    ):
        assert _search_tavily("test query") is None


def test_duckduckgo_formats_results():
    mock_result = [
        {"title": "DDG Result", "href": "https://ddg.example", "body": "DuckDuckGo snippet"}
    ]
    with patch("nally.tools.websearch.DDGS") as mock_ddgs:
        instance = MagicMock()
        instance.text.return_value = mock_result
        instance.__enter__.return_value = instance
        instance.__exit__.return_value = False
        mock_ddgs.return_value = instance

        result = _search_duckduckgo("test query")

    assert "DDG Result" in result
    assert "https://ddg.example" in result
    assert "DuckDuckGo snippet" in result


def test_duckduckgo_client_error_uses_html_fallback():
    with (
        patch("nally.tools.websearch.DDGS") as mock_ddgs,
        patch("nally.tools.websearch._search_fallback", return_value="HTML results") as fallback,
    ):
        mock_ddgs.return_value.__enter__.side_effect = RuntimeError("blocked")
        result = _search_duckduckgo("test query", 4)

    assert result == "HTML results"
    fallback.assert_called_once_with("test query", 4)


def test_web_search_tool_schema():
    tool = WebSearch()
    assert tool.name == "web_search"
    assert "query" in tool.parameters
    assert "num_results" in tool.parameters
    assert tool.parameters["query"]["required"] is True
    assert tool.permission == "safe"


def test_web_search_clamps_num_results_and_falls_back():
    tool = WebSearch()
    with (
        patch("nally.tools.websearch._search_tavily", return_value=None),
        patch("nally.tools.websearch._search_duckduckgo", return_value="fallback") as fallback,
    ):
        assert tool.execute(query="test", num_results=10) == "fallback"
        assert fallback.call_args.args == ("test", 5)

        tool.execute(query="test", num_results=0)
        assert fallback.call_args.args == ("test", 1)
