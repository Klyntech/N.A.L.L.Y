"""Tests for Tavily, Brave, and DuckDuckGo web search provider fallback."""

import os
from unittest.mock import MagicMock, patch

from nally.tools.websearch import (
    WebSearch,
    _search_brave,
    _search_duckduckgo,
    _search_tavily,
)


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


def test_brave_no_api_key_returns_none():
    with patch.dict(os.environ, {}, clear=True):
        assert _search_brave("test query") is None


def test_brave_success_formats_results_and_uses_auth_header():
    response = MagicMock()
    response.json.return_value = {
        "web": {
            "results": [
                {
                    "title": "Brave Result",
                    "url": "https://brave.example",
                    "description": "A useful Brave snippet.",
                }
            ]
        }
    }
    response.raise_for_status.return_value = None

    with (
        patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "brave-test-key"}),
        patch("nally.tools.websearch.httpx.get", return_value=response) as get,
    ):
        result = _search_brave("test query", 2)

    assert "Brave Result" in result
    assert "https://brave.example" in result
    assert "useful Brave snippet" in result
    assert get.call_args.kwargs["headers"]["X-Subscription-Token"] == "brave-test-key"
    assert get.call_args.args[0] == "https://api.search.brave.com/res/v1/web/search"
    assert get.call_args.kwargs["params"] == {"q": "test query", "count": 2}


def test_brave_http_error_returns_none():
    import httpx

    with (
        patch.dict(os.environ, {"BRAVE_SEARCH_API_KEY": "test-key"}),
        patch(
            "nally.tools.websearch.httpx.get",
            side_effect=httpx.ConnectError("connection failed"),
        ),
    ):
        assert _search_brave("test query") is None


def test_duckduckgo_formats_results():
    mock_result = [{"title": "DDG Result", "href": "https://ddg.example", "body": "DuckDuckGo snippet"}]
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


def test_web_search_tries_brave_after_tavily_fails():
    tool = WebSearch()
    with (
        patch("nally.tools.websearch._search_tavily", return_value=None),
        patch("nally.tools.websearch._search_brave", return_value="Brave results") as brave,
        patch("nally.tools.websearch._search_duckduckgo") as ddg,
    ):
        assert tool.execute(query="test", num_results=3) == "Brave results"
        brave.assert_called_once_with("test", 3)
        ddg.assert_not_called()


def test_web_search_clamps_num_results_and_falls_back():
    tool = WebSearch()
    with (
        patch("nally.tools.websearch._search_tavily", return_value=None),
        patch("nally.tools.websearch._search_brave", return_value=None),
        patch("nally.tools.websearch._search_duckduckgo", return_value="fallback") as fallback,
    ):
        assert tool.execute(query="test", num_results=10) == "fallback"
        assert fallback.call_args.args == ("test", 5)

        tool.execute(query="test", num_results=0)
        assert fallback.call_args.args == ("test", 1)



def test_html_fallback_uses_bing_when_duckduckgo_has_no_results():
    from nally.tools.websearch import _search_fallback

    ddg_response = MagicMock()
    ddg_response.text = "<html><body>No results</body></html>"
    ddg_response.raise_for_status.return_value = None
    bing_response = MagicMock()
    bing_response.text = (
        '<html><body><li class="b_algo"><h2><a href="https://example.com">'
        "Independent result</a></h2></li></body></html>"
    )
    bing_response.raise_for_status.return_value = None

    with patch("nally.tools.websearch.httpx.Client") as client_cls:
        client = MagicMock()
        client.get.side_effect = [ddg_response, bing_response]
        client_cls.return_value.__enter__.return_value = client
        client_cls.return_value.__exit__.return_value = False

        result = _search_fallback("test query", 2)

    assert "Independent result" in result
    assert "https://example.com" in result
    assert client.get.call_count == 2
