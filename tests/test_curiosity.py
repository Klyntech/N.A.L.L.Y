"""Tests for Nally Curiosity — proactive learning system."""

import json
import os
import sqlite3
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ── Interest Inference ────────────────────────────────────


class TestInterestInference:
    """Test interest extraction from behavioral signals."""

    def test_empty_inputs(self):
        from nally.curiosity.interests import infer_interests

        result = infer_interests([], [], [])
        assert result == []

    def test_profile_interests_weighted_high(self):
        from nally.curiosity.interests import infer_interests

        result = infer_interests(
            receipts=[], episodes=[], semantic_patterns=[],
            profile_interests='["python", "rust", "web"]',
        )
        assert "python" in result
        assert "rust" in result
        assert "web" in result

    def test_tool_receipts_extract_interests(self):
        from nally.curiosity.interests import infer_interests

        receipts = [
            {"tool": "run_code", "args": {"code": "import flask"}, "result": "ok"},
            {"tool": "run_code", "args": {"code": "import flask"}, "result": "ok"},
            {"tool": "web_search", "args": {"query": "python async patterns"}, "result": "results"},
        ]
        result = infer_interests(receipts=receipts, episodes=[], semantic_patterns=[])
        assert len(result) > 0

    def test_episode_topics_extracted(self):
        from nally.curiosity.interests import infer_interests

        episodes = [
            {"topic": "Docker deployment fix", "what_happened": "Fixed container", "tags": '["docker", "devops"]'},
            {"topic": "React component refactor", "what_happened": "Refactored hooks", "tags": '["react", "frontend"]'},
        ]
        result = infer_interests(receipts=[], episodes=episodes, semantic_patterns=[])
        assert "docker" in result
        assert "react" in result

    def test_semantic_patterns_contribute(self):
        from nally.curiosity.interests import infer_interests

        patterns = [
            {"pattern": "prefers vim keybindings", "confidence": 0.8},
            {"pattern": "uses typescript for frontend", "confidence": 0.6},
        ]
        result = infer_interests(receipts=[], episodes=[], semantic_patterns=patterns)
        assert any("vim" in r for r in result)
        assert any("typescript" in r for r in result)

    def test_stopwords_filtered(self):
        from nally.curiosity.interests import infer_interests

        episodes = [
            {"topic": "the and for but", "what_happened": "not a real topic", "tags": "[]"},
        ]
        result = infer_interests(receipts=[], episodes=episodes, semantic_patterns=[])
        for sw in ["the", "and", "for", "but", "not"]:
            assert sw not in result

    def test_max_interests_cap(self):
        from nally.curiosity.interests import infer_interests

        episodes = [{"topic": f"topic_{i}", "what_happened": "x", "tags": f'["tag_{i}"]'} for i in range(50)]
        result = infer_interests(receipts=[], episodes=episodes, semantic_patterns=[], max_interests=5)
        assert len(result) <= 5

    def test_json_array_profile(self):
        from nally.curiosity.interests import infer_interests

        result = infer_interests(
            [], [], [],
            profile_interests='["golang", "kubernetes"]',
        )
        assert "golang" in result
        assert "kubernetes" in result

    def test_comma_separated_profile(self):
        from nally.curiosity.interests import infer_interests

        result = infer_interests(
            [], [], [],
            profile_interests="python, rust, golang",
        )
        assert "python" in result
        assert "rust" in result
        assert "golang" in result


# ── Feed Fetchers ─────────────────────────────────────────


class TestFeedFetchers:
    """Test feed fetching with mocked HTTP."""

    def test_fetch_hacker_news_mocked(self):
        from nally.curiosity.feeds import fetch_hacker_news

        mock_resp = MagicMock()
        mock_resp.json.return_value = [1, 2]
        mock_resp.raise_for_status = MagicMock()

        mock_story = MagicMock()
        mock_story.json.return_value = {
            "title": "Test Story",
            "url": "https://example.com",
            "score": 50,
            "time": 1234567890,
            "type": "story",
        }
        mock_story.raise_for_status = MagicMock()

        with patch("nally.curiosity.feeds.requests.get", side_effect=[mock_resp, mock_story, mock_story]):
            items = fetch_hacker_news(limit=2)
        assert len(items) == 2
        assert items[0].source == "hacker_news"

    def test_fetch_devto_mocked(self):
        from nally.curiosity.feeds import fetch_devto

        mock_feed = MagicMock()
        mock_feed.bozo = False
        mock_feed.entries = [
            MagicMock(
                title="Test Article",
                link="https://dev.to/test",
                tags=[{"term": "python"}],
                published_parsed=(2026, 1, 1, 12, 0, 0, 0, 0, 0),
            )
        ]

        with patch("nally.curiosity.feeds.feedparser.parse", return_value=mock_feed):
            items = fetch_devto(limit=5)
        assert len(items) == 1
        assert items[0].source == "devto"
        assert "python" in items[0].tags

    def test_fetch_all_deduplicates(self):
        from nally.curiosity.feeds import FeedItem, fetch_all_feeds

        item1 = FeedItem(title="A", url="https://same.com", source="src1")
        item2 = FeedItem(title="A", url="https://same.com", source="src2")
        item3 = FeedItem(title="B", url="https://different.com", source="src1")

        with patch("nally.curiosity.feeds.fetch_hacker_news", return_value=[item1]):
            with patch("nally.curiosity.feeds.fetch_github_trending", return_value=[item2]):
                with patch("nally.curiosity.feeds.fetch_devto", return_value=[item3]):
                    items = fetch_all_feeds()
        urls = [i.url for i in items]
        assert len(urls) == len(set(urls))

    def test_fetch_hn_handles_error(self):
        from nally.curiosity.feeds import fetch_hacker_news

        with patch("nally.curiosity.feeds.requests.get", side_effect=Exception("timeout")):
            items = fetch_hacker_news()
        assert items == []


# ── Scanner Scoring & Triangulation ──────────────────────


class TestScanner:
    """Test scanner scoring and triangulation logic."""

    def _make_scanner(self):
        from nally.curiosity.scanner import CuriosityScanner
        return CuriosityScanner()

    def test_score_items_interest_overlap(self):
        scanner = self._make_scanner()
        items = [
            MagicMock(title="Python async guide", url="https://a.com", tags=["python", "async"], source="devto", score=0, published=time.time()),
            MagicMock(title="Rust tutorial", url="https://b.com", tags=["rust"], source="devto", score=0, published=time.time()),
        ]
        # Convert to dicts for _score_items
        item_dicts = [{"title": i.title, "url": i.url, "tags": i.tags, "source": i.source, "score": 0, "published": i.published} for i in items]
        scored = scanner._score_items(item_dicts, ["python", "web"])
        # Python item should score higher
        assert scored[0]["score"] >= scored[1]["score"]

    def test_triangulate_boosts_multi_source(self):
        scanner = self._make_scanner()
        items = [
            {"title": "A", "url": "https://same.com", "source": "hacker_news", "tags": [], "score": 0.5, "published": 0},
            {"title": "A", "url": "https://same.com", "source": "devto", "tags": [], "score": 0.3, "published": 0},
        ]
        result = scanner._triangulate(items)
        assert result[0]["triangulated"] is True
        assert result[0]["score"] > 0.5

    def test_triangulate_single_source_not_boosted(self):
        scanner = self._make_scanner()
        items = [
            {"title": "A", "url": "https://unique.com", "source": "hacker_news", "tags": [], "score": 0.5, "published": 0},
        ]
        result = scanner._triangulate(items)
        assert result[0]["triangulated"] is False
        assert result[0]["score"] == 0.5

    def test_status_returns_dict(self):
        scanner = self._make_scanner()
        status = scanner.get_status()
        assert "enabled" in status
        assert "running" in status
        assert "interval_seconds" in status


# ── Session Idle Detection ────────────────────────────────


class TestSessionIdle:
    """Test session manager idle detection."""

    def test_all_idle_when_no_sessions(self):
        from nally.agent.sessions import AgentSessionManager
        mgr = AgentSessionManager()
        assert mgr.all_idle() is True

    def test_seconds_since_last_activity_zero(self):
        from nally.agent.sessions import AgentSessionManager
        mgr = AgentSessionManager()
        assert mgr.seconds_since_last_activity() == 0

    def test_active_session_ids_empty(self):
        from nally.agent.sessions import AgentSessionManager
        mgr = AgentSessionManager()
        assert mgr.active_session_ids() == []


# ── Store TTL ─────────────────────────────────────────────


class TestStoreTTL:
    """Test memory store TTL and expiry."""

    def test_remember_with_ttl(self, tmp_dir):
        from nally.memory.store import MemoryRepository
        db = Path(tmp_dir) / "test_ttl.db"
        store = MemoryRepository(db_path=db)
        result = store.remember("ttl_key", "ttl_value", ttl_days=1)
        assert "Remembered" in result

        # Should be recalled immediately
        val = store.recall(key="ttl_key")
        assert val == "ttl_value"

    def test_prune_expired(self, tmp_dir):
        from nally.memory.store import MemoryRepository
        from datetime import datetime, timedelta
        db = Path(tmp_dir) / "test_prune.db"
        store = MemoryRepository(db_path=db)

        # Insert a memory with expires_at in the past
        now = datetime.now()
        past = (now - timedelta(days=1)).isoformat()
        with store._connection() as conn:
            conn.execute(
                "INSERT INTO memories (key, value, category, confidence, mention_count, created, last_confirmed, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("expired_key", "expired_val", "curiosity", 0.5, 1, now.isoformat(), now.isoformat(), past),
            )

        # Insert a memory without expiry
        with store._connection() as conn:
            conn.execute(
                "INSERT INTO memories (key, value, category, confidence, mention_count, created, last_confirmed, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("valid_key", "valid_val", "curiosity", 0.5, 1, now.isoformat(), now.isoformat(), None),
            )

        pruned = store.prune_expired()
        assert pruned == 1

        # Expired should be gone
        val = store.recall(key="expired_key")
        assert val is None

        # Valid should still be there
        val = store.recall(key="valid_key")
        assert val == "valid_val"

    def test_recall_skips_expired_by_default(self, tmp_dir):
        from nally.memory.store import MemoryRepository
        from datetime import datetime, timedelta
        db = Path(tmp_dir) / "test_recall.db"
        store = MemoryRepository(db_path=db)

        now = datetime.now()
        past = (now - timedelta(days=1)).isoformat()
        future = (now + timedelta(days=30)).isoformat()

        with store._connection() as conn:
            conn.execute(
                "INSERT INTO memories (key, value, category, confidence, mention_count, created, last_confirmed, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("expired", "val1", "test", 0.5, 1, now.isoformat(), now.isoformat(), past),
            )
            conn.execute(
                "INSERT INTO memories (key, value, category, confidence, mention_count, created, last_confirmed, expires_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("active", "val2", "test", 0.5, 1, now.isoformat(), now.isoformat(), future),
            )

        # Default: skip expired
        result = store.recall(category="test")
        assert "expired" not in result
        assert "active" in result

        # include_expired=True: show both
        result = store.recall(category="test", include_expired=True)
        assert "expired" in result
        assert "active" in result

    def test_backfill_expires_at(self, tmp_dir):
        """Test that existing DBs without expires_at column get it added."""
        from nally.memory.store import _backfill_expires_at_column
        db = Path(tmp_dir) / "test_backfill.db"

        # Create DB without expires_at column (minimal schema, no FTS)
        conn = sqlite3.connect(str(db))
        conn.execute("""CREATE TABLE memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            key TEXT NOT NULL,
            value TEXT NOT NULL,
            category TEXT DEFAULT 'general',
            confidence REAL DEFAULT 0.5,
            mention_count INTEGER DEFAULT 1,
            created TEXT NOT NULL,
            last_confirmed TEXT NOT NULL,
            deleted INTEGER DEFAULT 0
        )""")
        conn.execute("INSERT INTO memories (key, value, category, confidence, mention_count, created, last_confirmed) VALUES (?, ?, ?, ?, ?, ?, ?)",
                      ("old_key", "old_val", "general", 0.5, 1, "2026-01-01", "2026-01-01"))
        conn.commit()

        # Run backfill directly
        _backfill_expires_at_column(conn)

        # Verify the column was added
        cols = [row[1] for row in conn.execute("PRAGMA table_info(memories)").fetchall()]
        assert "expires_at" in cols

        # Verify old data is still there
        row = conn.execute("SELECT key, value FROM memories WHERE key = 'old_key'").fetchone()
        assert row == ("old_key", "old_val")
        conn.close()
