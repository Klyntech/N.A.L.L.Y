"""Fetch Tool — HTTP GET/POST with readability extraction.

Fetches web pages and returns their content. Strips HTML to clean text
using readability for article extraction, falls back to basic tag stripping.
"""

import logging
import os
import re
from urllib.parse import urlparse

import httpx

from .registry import Tool
from ._retry import retry_transient

logger = logging.getLogger("nally.tools.fetch")

MAX_OUTPUT = 50000
DEFAULT_TIMEOUT = 15.0
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"

# SSL verification — disabled by default for proxy environments, toggle with NALLY_VERIFY_SSL
VERIFY_SSL = os.environ.get("NALLY_VERIFY_SSL", "false").lower() in ("true", "1", "yes")


def _strip_html(html: str) -> str:
    """Basic HTML to text conversion — no dependencies."""
    # Remove script and style blocks
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Block elements get newlines
    text = re.sub(r"<(br|hr|/p|/div|/h[1-6]|/li|/tr)[^>]*>", "\n", text, flags=re.IGNORECASE)
    # Strip remaining tags
    text = re.sub(r"<[^>]+>", "", text)
    # Decode common entities
    for entity, char in [("&amp;", "&"), ("&lt;", "<"), ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'"), ("&nbsp;", " ")]:
        text = text.replace(entity, char)
    # Collapse whitespace
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse multiple newlines
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _extract_with_readability(html: str) -> str | None:
    """Try to extract main article content using readability-lxml."""
    try:
        from readability import Document

        doc = Document(html)
        title = doc.title()
        summary = doc.summary()
        text = _strip_html(summary)
        if title and len(text) > 100:
            return f"Title: {title}\n\n{text}"
        return text if len(text) > 100 else None
    except ImportError:
        return None
    except Exception:
        return None


def _fetch_url(url: str, method: str = "GET", body: str = None, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Fetch a URL and return readable text content."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Error: Only http/https URLs supported, got '{parsed.scheme or 'none'}'"

    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }

    proxy = None
    from ..config import HTTP_PROXY, HTTPS_PROXY

    if HTTPS_PROXY:
        proxy = HTTPS_PROXY
    elif HTTP_PROXY:
        proxy = HTTP_PROXY

    def _do_fetch():
        with httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            proxy=proxy,
            verify=VERIFY_SSL,
        ) as client:
            if method.upper() == "POST" and body is not None:
                headers["Content-Type"] = "application/json"
                resp = client.post(url, headers=headers, content=body)
            else:
                resp = client.get(url, headers=headers)

            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            if "text/html" not in content_type and "application/xhtml" not in content_type:
                # Non-HTML content — return raw (truncated)
                text = resp.text[:MAX_OUTPUT]
                if len(resp.text) > MAX_OUTPUT:
                    text += f"\n... [truncated, {len(resp.text)} chars total]"
                return text

            html = resp.text

            # Try readability first, fall back to basic stripping
            text = _extract_with_readability(html)
            if not text:
                text = _strip_html(html)

            # Add source info
            source = parsed.netloc
            if len(text) > MAX_OUTPUT:
                text = text[:MAX_OUTPUT] + f"\n... [truncated, {len(text)} chars total]"

            return f"Source: {source}\n\n{text}"

    try:
        result, exc = retry_transient(
            _do_fetch,
            max_attempts=2,
            backoff_base=1.0,
            logger_name="nally.tools.fetch",
        )
        if exc:
            # Map known exceptions to user-friendly messages
            if isinstance(exc, httpx.TimeoutException):
                return f"Error: Request timed out after {timeout}s for {url}"
            elif isinstance(exc, httpx.HTTPStatusError):
                return f"Error: HTTP {exc.response.status_code} from {url}"
            elif isinstance(exc, httpx.ConnectError):
                return f"Error: Could not connect to {parsed.netloc} (DNS failure or server down)"
            else:
                return f"Error: {type(exc).__name__}: {exc}"
        return result
    except Exception as e:
        return f"Error: {type(e).__name__}: {e}"


class FetchTool(Tool):
    """Fetch web pages and return their content as readable text."""

    def __init__(self):
        super().__init__(
            name="fetch",
            description=(
                "Fetch a web page and return its text content. "
                "Use for reading articles, documentation, or any web page you need the full content of. "
                "Returns clean text with HTML stripped."
            ),
            permission="safe",
            parameters={
                "url": {
                    "type": "string",
                    "description": "The URL to fetch (must start with http:// or https://)",
                    "required": True,
                },
                "method": {
                    "type": "string",
                    "description": "HTTP method: GET (default) or POST",
                    "default": "GET",
                    "enum": ["GET", "POST"],
                },
                "body": {
                    "type": "string",
                    "description": "Request body for POST requests (JSON string)",
                },
            },
        )

    def execute(self, url: str, method: str = "GET", body: str = None) -> str:
        return _fetch_url(url, method=method, body=body)
