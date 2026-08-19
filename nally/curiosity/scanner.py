"""Nally Curiosity Scanner — proactive learning from idle cycles.

Runs as a background thread, fetching dev feeds during idle periods.
Matches items against inferred user interests, triangulates across sources,
and stores findings as memories with 14-day TTL.

Confidence starts at 0.4. Only boosts to 0.7+ if referenced in a user session.
"""

import json
import os
import threading
import time
from typing import Any, Dict, List, Optional

from ..utils.logger import logger

# ── Config ────────────────────────────────────────────────

DEFAULT_INTERVAL = 6 * 3600  # 6 hours
IDLE_THRESHOLD = 300  # 5 minutes before considering idle
DEFAULT_TTL_DAYS = 14
INITIAL_CONFIDENCE = 0.4
REFERENCE_BOOST = 0.3  # 0.4 + 0.3 = 0.7 on user reference
CONFIDENCE_CEILING = 0.9
TRIANGULATION_BONUS = 0.15  # extra confidence for multi-source items


class CuriosityScanner:
    """Background scanner that fetches dev content during idle periods."""

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._interval = int(os.environ.get("NALLY_CURIOSITY_INTERVAL", DEFAULT_INTERVAL))
        self._enabled = os.environ.get("NALLY_CURIOSITY_ENABLED", "true").lower() in ("true", "1", "yes")

    def start(self, interval: Optional[int] = None):
        """Start background scanner thread."""
        if not self._enabled:
            logger.info("Curiosity scanner disabled (NALLY_CURIOSITY_ENABLED=false)")
            return
        if self._running:
            return
        if interval:
            self._interval = interval
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True, name="curiosity")
        self._thread.start()
        logger.info(f"Curiosity scanner started (interval: {self._interval}s)")

    def stop(self):
        """Stop background scanner."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Curiosity scanner stopped")

    def _loop(self):
        """Background loop — wait for idle, then scan."""
        while self._running:
            time.sleep(60)  # Check every minute
            try:
                if self._should_scan():
                    self._scan()
            except Exception as e:
                logger.error(f"Curiosity scan failed: {e}")

    def _should_scan(self) -> bool:
        """Check if we should scan now (idle + interval elapsed)."""
        from ..agent.sessions import session_manager

        if not session_manager.all_idle(idle_threshold=IDLE_THRESHOLD):
            return False

        last_scan = self._get_last_scan_time()
        if time.time() - last_scan < self._interval:
            return False

        return True

    def _scan(self):
        """Run a curiosity scan cycle."""
        logger.info("Curiosity scan starting...")

        # 1. Infer interests from behavioral signals
        from ..memory import memory_store
        from ..tools.receipts import receipt_store
        from .interests import infer_interests

        recent_receipts = [r.to_dict() for r in receipt_store.get_recent(limit=50)]
        recent_episodes = memory_store.search_episodes(limit=20)
        semantic = memory_store.recall_semantic(min_confidence=0.3)
        profile = memory_store.recall(key="interests", category="profile")

        interests = infer_interests(
            receipts=recent_receipts,
            episodes=recent_episodes,
            semantic_patterns=semantic,
            profile_interests=profile,
        )

        if not interests:
            logger.info("No interests inferred, skipping scan")
            self._set_last_scan_time()
            return

        # 2. Fetch feeds
        from .feeds import fetch_all_feeds

        items = fetch_all_feeds(interests=interests, limit_per_source=15)
        if not items:
            logger.info("No feed items fetched")
            self._set_last_scan_time()
            return

        # Convert FeedItem objects to dicts
        items = [item.to_dict() if hasattr(item, "to_dict") else item for item in items]

        # 3. Score and filter items
        scored = self._score_items(items, interests)

        # 4. Triangulate — items from multiple sources get confidence boost
        triangulated = self._triangulate(scored)

        # 5. Store as memories with TTL
        stored = 0
        for item in triangulated:
            if item["score"] < 0.3:
                continue
            if self._already_stored(item["url"]):
                continue
            self._store_finding(item)
            stored += 1

        self._set_last_scan_time()
        logger.info(f"Curiosity scan complete: {len(items)} fetched, {stored} stored")

    def _score_items(self, items, interests: List[str]) -> List[Dict]:
        """Score feed items based on interest match and source quality."""
        scored = []
        interest_set = set(i.lower() for i in interests)

        for item in items:
            score = 0.0
            tags = set(t.lower() for t in item.get("tags", []))
            title_lower = item.get("title", "").lower()

            # Interest overlap
            overlap = tags & interest_set
            score += len(overlap) * 0.2

            # Title keyword match
            for interest in interests:
                if interest.lower() in title_lower:
                    score += 0.15

            # Source quality bonus
            if item.get("source") == "hacker_news" and item.get("score", 0) > 100:
                score += 0.2
            elif item.get("source") == "github_trending":
                score += 0.1

            # Recency bonus (within last 24h)
            published = item.get("published", 0)
            if published and (time.time() - published) < 86400:
                score += 0.1

            scored.append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "source": item.get("source", ""),
                "tags": list(tags),
                "score": min(score, 1.0),
                "published": published,
            })

        scored.sort(key=lambda x: x["score"], reverse=True)
        return scored[:30]  # Top 30

    def _triangulate(self, items: List[Dict]) -> List[Dict]:
        """Boost confidence for items appearing from multiple sources."""
        url_sources: Dict[str, List[str]] = {}
        for item in items:
            url = item["url"]
            if url not in url_sources:
                url_sources[url] = []
            url_sources[url].append(item["source"])

        for item in items:
            sources = url_sources.get(item["url"], [])
            if len(sources) >= 2:
                item["score"] = min(item["score"] + TRIANGULATION_BONUS, 1.0)
                item["triangulated"] = True
            else:
                item["triangulated"] = False

        return items

    def _already_stored(self, url: str) -> bool:
        """Check if we've already stored this finding."""
        from ..memory import memory_store

        result = memory_store.recall(search=url, category="curiosity")
        return bool(result)

    def _store_finding(self, item: Dict):
        """Store a curiosity finding as a memory with TTL."""
        from ..memory import memory_store

        key = f"curiosity:{item['source']}:{item['url'][-60:]}"
        value = json.dumps({
            "title": item["title"],
            "url": item["url"],
            "source": item["source"],
            "tags": item["tags"],
            "triangulated": item.get("triangulated", False),
        }, ensure_ascii=False)

        memory_store.remember(
            key=key,
            value=value,
            category="curiosity",
            confidence=INITIAL_CONFIDENCE,
            ttl_days=DEFAULT_TTL_DAYS,
        )

    def boost_confidence(self, url: str, boost: float = REFERENCE_BOOST):
        """Boost confidence when a curiosity finding is referenced in a session."""
        from ..memory import memory_store

        result = memory_store.recall(search=url, category="curiosity")
        if result:
            # Find and boost the memory
            with memory_store._connection() as conn:
                rows = conn.execute(
                    "SELECT id, confidence FROM memories WHERE key LIKE ? AND category = 'curiosity' AND deleted = 0",
                    (f"%{url[-60:]}",),
                ).fetchall()
                for row in rows:
                    new_conf = min(row["confidence"] + boost, CONFIDENCE_CEILING)
                    conn.execute(
                        "UPDATE memories SET confidence = ? WHERE id = ?",
                        (new_conf, row["id"]),
                    )

    def _get_last_scan_time(self) -> float:
        """Get timestamp of last scan."""
        from ..memory import memory_store

        val = memory_store.recall(key="curiosity:last_scan")
        if val:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
        return 0

    def _set_last_scan_time(self):
        """Record current time as last scan."""
        from ..memory import memory_store

        memory_store.remember(
            key="curiosity:last_scan",
            value=str(time.time()),
            category="curiosity",
            confidence=1.0,
        )

    def get_status(self) -> Dict[str, Any]:
        """Return scanner status for health endpoints."""
        return {
            "enabled": self._enabled,
            "running": self._running,
            "interval_seconds": self._interval,
            "last_scan": self._get_last_scan_time(),
        }


# ── Module Singleton ──────────────────────────────────────

curiosity_scanner = CuriosityScanner()
