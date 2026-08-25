"""Web Search Tool — Parallel.ai primary, DuckDuckGo fallback.

Searches the web for current information. Tracks monthly usage
and falls back to DuckDuckGo when the Parallel.ai quota is exhausted.
"""

import logging
import os
import sqlite3
import threading
from datetime import datetime

import httpx

try:
    from duckduckgo_search import DDGS
except ImportError:
    DDGS = None
from .registry import Tool
from ._retry import retry_transient

logger = logging.getLogger("nally.tools.websearch")

# Monthly limit for Parallel.ai free tier
PARALLEL_MONTHLY_LIMIT = 5000

# Serializes the quota check + increment so concurrent searches cannot both
# pass the limit check (read-then-increment race).
_quota_lock = threading.Lock()


def _get_db_path() -> str:
    """Get path to the usage tracking database."""
    from ..config import DATA_DIR

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return str(DATA_DIR / "nally.db")


def _ensure_usage_table(db_path: str):
    """Create web_search_usage table if it doesn't exist."""
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS web_search_usage (
            id INTEGER PRIMARY KEY,
            month TEXT NOT NULL,
            provider TEXT NOT NULL,
            count INTEGER DEFAULT 0,
            UNIQUE(month, provider)
        )
    """)
    conn.commit()
    conn.close()


def _get_monthly_count(db_path: str, provider: str) -> int:
    """Get the current month's search count for a provider."""
    month = datetime.now().strftime("%Y-%m")
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT count FROM web_search_usage WHERE month = ? AND provider = ?",
        (month, provider),
    ).fetchone()
    conn.close()
    return row[0] if row else 0


def _increment_monthly_count(db_path: str, provider: str):
    """Increment the current month's search count."""
    month = datetime.now().strftime("%Y-%m")
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        INSERT INTO web_search_usage (month, provider, count)
        VALUES (?, ?, 1)
        ON CONFLICT(month, provider) DO UPDATE SET count = count + 1
    """,
        (month, provider),
    )
    conn.commit()
    conn.close()


def _search_parallel(query: str, num_results: int = 3) -> str | None:
    """Search using Parallel.ai Search API. Returns formatted results or None on failure."""
    api_key = os.getenv("PARALLEL_API_KEY", "")
    if not api_key:
        return None

    db_path = _get_db_path()
    _ensure_usage_table(db_path)

    # Hold the quota lock across the check AND the increment so concurrent
    # searches cannot both pass the limit (audit Architecture Risk #4).
    _quota_lock.acquire()
    count = _get_monthly_count(db_path, "parallel")
    if count >= PARALLEL_MONTHLY_LIMIT:
        _quota_lock.release()
        logger.info(f"Parallel.ai monthly limit reached ({count}/{PARALLEL_MONTHLY_LIMIT}), using fallback")
        return None

    def _do_search():
        # Build search queries — generate 2 diverse queries from the user's question
        words = query.split()[:6]
        search_queries = [
            query,
            " ".join(words[:4]) if len(words) > 4 else query,
        ]

        resp = httpx.post(
            "https://api.parallel.ai/v1/search",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "objective": query,
                "search_queries": search_queries,
                "mode": "turbo",
            },
            timeout=10.0,
        )

        if resp.status_code != 200:
            # Raise on non-200 so retry_transient can detect transient errors (5xx, 429)
            resp.raise_for_status()

        return resp.json()

    try:
        result, exc = retry_transient(
            _do_search,
            max_attempts=3,
            backoff_base=1.0,
            logger_name="nally.tools.websearch.parallel",
        )

        if exc:
            _quota_lock.release()
            logger.warning(f"Parallel.ai search failed after retries: {type(exc).__name__}: {exc}")
            return None

        _increment_monthly_count(db_path, "parallel")
        _quota_lock.release()

        # Format results
        results = result.get("results", [])
        if not results:
            return "No results found."

        parts = []
        for i, r in enumerate(results[:num_results], 1):
            title = r.get("title", "Untitled")
            url = r.get("url", "")
            excerpts = r.get("excerpts", [])
            snippet = excerpts[0][:300] if excerpts else ""
            parts.append(f"[{i}] {title}\n{url}\n{snippet}")

        return "\n\n".join(parts)

    except Exception as e:
        if _quota_lock.locked():
            _quota_lock.release()
        logger.error(f"Parallel.ai search error: {type(e).__name__}: {e}")
        return None


def _search_duckduckgo(query: str, num_results: int = 3) -> str:
    """Search using DuckDuckGo (free, no API key). Returns formatted results."""
    if DDGS is None:
        logger.warning("duckduckgo-search not installed, falling back to curl search")
        return _search_fallback(query, num_results)

    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=num_results))

        if not results:
            return "No results found."

        parts = []
        for i, r in enumerate(results, 1):
            title = r.get("title", "Untitled")
            href = r.get("href", r.get("link", ""))
            body = r.get("body", r.get("snippet", ""))[:300]
            parts.append(f"[{i}] {title}\n{href}\n{body}")

        return "\n\n".join(parts)

    except Exception as e:
        logger.error(f"DuckDuckGo search error: {type(e).__name__}: {e}")
        return _search_fallback(query, num_results)


def _search_fallback(query: str, num_results: int = 3) -> str:
    """Last resort: use httpx to fetch search results from a public search engine."""
    import urllib.parse

    try:
        encoded = urllib.parse.quote_plus(query)
        url = f"https://lite.duckduckgo.com/lite/?q={encoded}"

        with httpx.Client(timeout=10, follow_redirects=True) as client:
            response = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
            response.raise_for_status()
            text = response.text

        # Extract simple text results from the HTML
        import re

        links = re.findall(r'<a[^>]+class="result-link"[^>]*href="([^"]+)"[^>]*>([^<]+)</a>', text)
        snippets = re.findall(r'<td class="result-snippet">(.*?)</td>', text, re.DOTALL)

        if links:
            parts = []
            for i, (href, title) in enumerate(links[:num_results], 1):
                snippet = snippets[i - 1].strip()[:300] if i - 1 < len(snippets) else ""
                snippet = re.sub(r"<[^>]+>", "", snippet)  # Strip HTML tags
                parts.append(f"[{i}] {title.strip()}\n{href}\n{snippet}")
            return "\n\n".join(parts)

        return f"Web search unavailable. Try searching manually for: {query}"

    except Exception:
        return f"Web search unavailable. Try searching manually for: {query}"


class WebSearch(Tool):
    """Search the web for current information using Parallel.ai with DuckDuckGo fallback."""

    def __init__(self):
        now = datetime.now()
        super().__init__(
            name="web_search",
            description=(
                f"Search the web for current information. Today is {now.strftime('%A, %B %d, %Y')}. "
                "Use for factual questions, news, events, or anything you're unsure about. "
                "Returns titles, URLs, and snippets from web results."
            ),
            permission="safe",
            parameters={
                "query": {
                    "type": "string",
                    "description": "The search query — be specific for better results. Always use the current year.",
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
        """Execute a web search. Tries Parallel.ai first, falls back to DuckDuckGo."""
        num_results = max(1, min(5, num_results))

        # Try Parallel.ai first
        result = _search_parallel(query, num_results)
        if result:
            return result

        # Fall back to DuckDuckGo
        logger.info("Falling back to DuckDuckGo search")
        return _search_duckduckgo(query, num_results)
