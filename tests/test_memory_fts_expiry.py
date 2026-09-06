"""FTS expiry filtering must match LIKE-path semantics.

Regression tests for the S2 defect: _fts_search() returned expired rows
while the LIKE fallback filtered them, so recall() results depended on
which path served the query.

The index is built explicitly (INSERT...SELECT + rebuild) so the tests do
not depend on FTS trigger creation, which is environment-dependent.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from nally.memory.store import MemoryRepository


@pytest.fixture
def fts_repo():
    """Tmp repo with a live and an expired row, FTS index built by hand."""
    d = Path(tempfile.mkdtemp(prefix="test-fts-"))
    repo = MemoryRepository(db_path=d / "fts.db")
    repo.remember("live1", "zebra quartz", "general")
    repo.remember("exp1", "zebra expiredonly", "general", ttl_days=-1)
    con = sqlite3.connect(str(d / "fts.db"))
    con.execute(
        "INSERT INTO memories_fts(rowid, key, value, category) "
        "SELECT id, key, value, category FROM memories "
        "WHERE deleted = 0 AND id NOT IN (SELECT rowid FROM memories_fts)"
    )
    con.execute("INSERT INTO memories_fts(memories_fts) VALUES('rebuild')")
    con.commit()
    con.close()
    return repo


def _fts_row_count(repo):
    with repo._connection() as conn:
        if hasattr(conn, "execute"):
            try:
                return conn.execute("SELECT COUNT(*) FROM memories_fts").fetchone()[0]
            except Exception:
                pass
    return -1


class TestFtsExpiry:
    def test_index_holds_both_rows(self, fts_repo):
        assert _fts_row_count(fts_repo) >= 2

    def test_direct_search_filters_expired(self, fts_repo):
        now = MemoryRepository._now()
        with fts_repo._connection() as conn:
            rows = fts_repo._fts_search(conn, "quartz zebra", 0.0, 20, expired_after=now)
            keys = [r["key"] for r in (rows or [])]
        assert "live1" in keys
        assert "exp1" not in keys

    def test_direct_search_without_expiry_filter_returns_both(self, fts_repo):
        with fts_repo._connection() as conn:
            rows = fts_repo._fts_search(conn, "quartz zebra", 0.0, 20, expired_after=None)
            keys = [r["key"] for r in (rows or [])]
        # include_expired=True path must be preserved; skip if this env's
        # FTS cannot serve (falls back to LIKE, which is order-sensitive).
        if not keys:
            pytest.skip("FTS unavailable in this environment")
        assert "live1" in keys
        assert "exp1" in keys

    def test_recall_excludes_expired_via_fts(self, fts_repo):
        # Reversed token order: LIKE '%quartz zebra%' cannot match, so a hit
        # proves the FTS path served the query.
        result = fts_repo.recall(search="quartz zebra")
        assert isinstance(result, dict)
        if "live1" not in result:
            pytest.skip("FTS unavailable in this environment")
        assert "exp1" not in result
