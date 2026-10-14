"""Web search tool: Tavily primary, Brave secondary, DuckDuckGo fallback.

Tavily and Brave are used when their API keys are configured. DuckDuckGo is the
keyless fallback, with a lightweight HTML fallback if its Python client fails.
"""

import logging
import os
import urllib.parse

import httpx

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        DDGS = None

from .registry import Tool

logger = logging.getLogger("nally.tools.websearch")
TAVILY_SEARCH_URL = "https://api.tavily.com/search"
BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


def _format_results(results: list[dict], num_results: int) -> str:
    """Format normalized search results for the agent."""
    if not results:
        return "No results found."

    parts = []
    for index, result in enumerate(results[:num_results], 1):
        title = result.get("title") or "Untitled"
        url = result.get("url") or result.get("href") or result.get("link") or ""
        snippet = (
            result.get("content")
            or result.get("description")
            or result.get("body")
            or result.get("snippet")
            or (result.get("excerpts") or [""])[0]
        )
        parts.append(f"[{index}] {title}\n{url}\n{snippet[:500]}")
    return "\n\n".join(parts)


def _search_tavily(query: str, num_results: int = 3) -> str | None:
    """Search Tavily. Return None when unconfigured or unavailable."""
    api_key = os.getenv("TAVILY_API_KEY", "").strip()
    if not api_key:
        logger.info("Tavily API key is not configured; trying Brave")
        return None

    try:
        response = httpx.post(
            TAVILY_SEARCH_URL,
            json={
                "api_key": api_key,
                "query": query,
                "search_depth": "basic",
                "max_results": num_results,
                "include_answer": False,
            },
            timeout=15.0,
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        if not results:
            logger.info("Tavily returned zero results; trying Brave")
            return None
        return _format_results(results, num_results)
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        logger.warning("Tavily search failed (%s, HTTP %s); trying Brave", type(exc).__name__, status)
        return None


def _search_brave(query: str, num_results: int = 3) -> str | None:
    """Search Brave Search API. Return None when unconfigured or unavailable."""
    api_key = os.getenv("BRAVE_SEARCH_API_KEY", "").strip()
    if not api_key:
        logger.info("Brave Search API key is not configured; using DuckDuckGo if needed")
        return None

    try:
        response = httpx.get(
            BRAVE_SEARCH_URL,
            headers={
                "X-Subscription-Token": api_key,
                "Accept": "application/json",
            },
            params={"q": query, "count": num_results},
            timeout=15.0,
        )
        response.raise_for_status()
        payload = response.json()
        results = payload.get("web", {}).get("results", [])
        if not results:
            logger.info("Brave returned zero results; trying DuckDuckGo")
            return None
        return _format_results(results, num_results)
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        logger.warning("Brave search failed (%s, HTTP %s); trying DuckDuckGo", type(exc).__name__, status)
        return None


def _search_duckduckgo(query: str, num_results: int = 3) -> str:
    """Search DuckDuckGo through the maintained ddgs package."""
    if DDGS is None:
        logger.warning("Neither ddgs nor duckduckgo-search is installed; using HTML fallback")
        return _search_fallback(query, num_results)

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=num_results))
        if results:
            return _format_results(results, num_results)
        logger.info("DuckDuckGo returned zero results; trying HTML fallback")
    except Exception as exc:
        logger.warning("DuckDuckGo client failed (%s); trying HTML fallback", type(exc).__name__)

    return _search_fallback(query, num_results)


def _search_fallback(query: str, num_results: int = 3) -> str:
    """Last resort: try DuckDuckGo Lite, then an independent Bing HTML endpoint."""
    encoded_query = urllib.parse.quote_plus(query)
    providers = [
        (
            "DuckDuckGo Lite",
            f"https://lite.duckduckgo.com/lite/?q={encoded_query}",
            ("a.result-link", "a.result__a"),
        ),
        (
            "Bing",
            f"https://www.bing.com/search?q={encoded_query}",
            (".b_algo h2 a",),
        ),
    ]
    errors = []

    for provider, url, selectors in providers:
        try:
            with httpx.Client(timeout=12.0, follow_redirects=True) as client:
                response = client.get(url, headers={"User-Agent": "Mozilla/5.0 (compatible; Nally/1.0)"})
                response.raise_for_status()

            from bs4 import BeautifulSoup

            soup = BeautifulSoup(response.text, "html.parser")
            results = []
            seen_urls = set()
            for selector in selectors:
                for anchor in soup.select(selector):
                    href = anchor.get("href", "")
                    title = anchor.get_text(" ", strip=True)
                    if (
                        title
                        and href.startswith(("http://", "https://"))
                        and href not in seen_urls
                    ):
                        results.append({"title": title, "url": href, "content": ""})
                        seen_urls.add(href)
                    if len(results) >= num_results:
                        break
                if len(results) >= num_results:
                    break

            if results:
                logger.info("Web search fallback succeeded with %s", provider)
                return _format_results(results, num_results)
            errors.append(f"{provider}: no parseable results")
            logger.warning("%s fallback returned no parseable result links", provider)
        except Exception as exc:
            errors.append(f"{provider}: {type(exc).__name__}")
            logger.warning("%s fallback failed (%s)", provider, type(exc).__name__)

    detail = "; ".join(errors)
    return f"Error: Web search fallback providers failed ({detail}). Query: {query}"


class WebSearch(Tool):
    """Search the web using Tavily, Brave, and DuckDuckGo fallbacks."""

    def __init__(self):
        super().__init__(
            name="web_search",
            description=(
                "Search the web for current information using Tavily first, Brave Search when configured, "
                "then DuckDuckGo as a free fallback. Use for factual questions, news, events, or anything "
                "you're unsure about. Returns titles, URLs, and snippets."
            ),
            permission="safe",
            parameters={
                "query": {
                    "type": "string",
                    "description": "Specific web search query. Include the current year for time-sensitive topics.",
                    "required": True,
                },
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return (1-5, default 3)",
                    "default": 3,
                },
            },
        )

    def execute(self, query: str, num_results: int = 3) -> str:
        """Try Tavily, then Brave, then DuckDuckGo and its HTML fallback."""
        num_results = max(1, min(5, num_results))
        result = _search_tavily(query, num_results)
        if result:
            return result
        result = _search_brave(query, num_results)
        if result:
            return result
        logger.info("Using DuckDuckGo fallback for web search")
        return _search_duckduckgo(query, num_results)
