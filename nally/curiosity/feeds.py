"""Feed Fetchers — pull dev-relevant content from multiple sources.

Each fetcher returns a list of FeedItem dicts:
    {title, url, source, tags, score, published}

Triangulation: same item from multiple sources = confirmed signal.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import feedparser
import requests

logger = logging.getLogger("nally.curiosity.feeds")

_REQUEST_TIMEOUT = 15  # seconds


@dataclass
class FeedItem:
    """A single item from a feed source."""
    title: str = ""
    url: str = ""
    source: str = ""
    tags: List[str] = field(default_factory=list)
    score: float = 0.0
    published: float = 0.0

    def to_dict(self) -> Dict:
        return {
            "title": self.title,
            "url": self.url,
            "source": self.source,
            "tags": self.tags,
            "score": self.score,
            "published": self.published,
        }


def fetch_hacker_news(limit: int = 20) -> List[FeedItem]:
    """Fetch top stories from Hacker News (official API, no key required)."""
    try:
        resp = requests.get(
            "https://hacker-news.firebaseio.com/v0/topstories.json",
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        story_ids = resp.json()[:limit]
    except Exception as e:
        logger.warning(f"HN top stories failed: {e}")
        return []

    items = []
    for sid in story_ids:
        try:
            story = requests.get(
                f"https://hacker-news.firebaseio.com/v0/item/{sid}.json",
                timeout=_REQUEST_TIMEOUT,
            ).json()
            if not story or story.get("type") != "story":
                continue
            items.append(FeedItem(
                title=story.get("title", ""),
                url=story.get("url", f"https://news.ycombinator.com/item?id={sid}"),
                source="hacker_news",
                tags=_extract_tags(story.get("title", "")),
                score=float(story.get("score", 0)),
                published=float(story.get("time", 0)),
            ))
        except Exception:
            continue

    return items


def fetch_github_trending(language: str = "", since: str = "daily", limit: int = 20) -> List[FeedItem]:
    """Fetch trending repos from GitHub (unofficial — scrapes trending page)."""
    url = "https://github.com/trending"
    if language:
        url += f"/{language}"
    url += f"?since={since}"

    try:
        resp = requests.get(url, timeout=_REQUEST_TIMEOUT, headers={
            "User-Agent": "Nally-Curiosity/1.0",
            "Accept": "text/html",
        })
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"GitHub trending failed: {e}")
        return []

    # Simple HTML parsing — no BS4 dependency
    items = []
    lines = resp.text.split("\n")
    repo_count = 0
    for i, line in enumerate(lines):
        if 'class="Box-row"' in line or 'h2 class="h3 lh-condensed"' in line:
            # Extract repo name from nearby h2 tag
            for j in range(max(0, i - 5), min(len(lines), i + 10)):
                if "/<a" in lines[j] or "href=/" in lines[j]:
                    import re
                    match = re.search(r'href="(/[^"]+)"', lines[j])
                    if match:
                        repo_path = match.group(1).strip("/")
                        parts = repo_path.split("/")
                        if len(parts) == 2:
                            items.append(FeedItem(
                                title=repo_path,
                                url=f"https://github.com/{repo_path}",
                                source="github_trending",
                                tags=_extract_tags(repo_path),
                                score=0.0,
                                published=time.time(),
                            ))
                            repo_count += 1
                            if repo_count >= limit:
                                return items
                            break

    return items


def fetch_devto(tag: str = "", limit: int = 20) -> List[FeedItem]:
    """Fetch top articles from dev.to (RSS or API, no key required)."""
    url = "https://dev.to/feed"
    if tag:
        url += f"?tag={tag}"

    try:
        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            logger.warning(f"dev.to RSS parse failed: {feed.bozo_exception}")
            return []
    except Exception as e:
        logger.warning(f"dev.to feed failed: {e}")
        return []

    items = []
    for entry in feed.entries[:limit]:
        tags = []
        if hasattr(entry, "tags"):
            tags = [t.get("term", "") for t in entry.tags if t.get("term")]

        published = 0
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            import calendar
            published = calendar.timegm(entry.published_parsed)

        items.append(FeedItem(
            title=entry.get("title", ""),
            url=entry.get("link", ""),
            source="devto",
            tags=tags or _extract_tags(entry.get("title", "")),
            score=0.0,
            published=published,
        ))

    return items


def _extract_tags(text: str) -> List[str]:
    """Extract potential tags/keywords from text."""
    import re
    words = re.findall(r'[a-zA-Z][a-zA-Z0-9+#_.-]+', text.lower())
    # Keep words that look like tech terms
    stop = {"the", "and", "for", "with", "from", "that", "this", "are", "was", "not", "but", "how", "why", "what", "when", "where", "new", "your", "has", "have", "its", "can", "will", "all"}
    return [w for w in words if w not in stop and len(w) >= 2][:8]


def fetch_all_feeds(interests: Optional[List[str]] = None, limit_per_source: int = 15) -> List[FeedItem]:
    """Fetch from all sources, optionally filtered by interests.

    Returns deduplicated items across all sources.
    """
    all_items: List[FeedItem] = []

    # HN — always fetch top stories
    all_items.extend(fetch_hacker_news(limit=limit_per_source))

    # GitHub trending — fetch main + interest-specific languages
    all_items.extend(fetch_github_trending(limit=limit_per_source))

    # dev.to — fetch top + interest-tagged
    all_items.extend(fetch_devto(limit=limit_per_source))
    if interests:
        for interest in interests[:3]:
            all_items.extend(fetch_devto(tag=interest, limit=5))

    # Deduplicate by URL
    seen_urls = set()
    deduped = []
    for item in all_items:
        if item.url and item.url not in seen_urls:
            seen_urls.add(item.url)
            deduped.append(item)

    return deduped
