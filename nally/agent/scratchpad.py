"""Nally Scratchpad — per-request working memory.

This is a task-local, ephemeral state object that persists across tool calls
within a single request. It is NOT the long-term memory store — clearly
separated in code and storage so long-term memory never gets polluted by
task-local scratch state.

At end of task, an explicit write-back step decides what (if anything)
gets written to long-term memory. This is a deliberate write, never an
automatic dump of the scratchpad.

Storage: SQLite table `scratchpads` — one row per task, deleted after
write-back or on task completion.
"""

import json
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import DATA_DIR, TURSO_URL, TURSO_TOKEN
from ..utils.logger import logger


@dataclass
class Scratchpad:
    """Per-request working memory. Ephemeral, task-local, crash-safe.

    Fields:
        id: Unique scratchpad ID (auto-generated).
        objective: The user's original request/goal.
        constraints: Known limitations or requirements.
        facts: Discovered facts relevant to the task.
        assumptions: Working assumptions (to be verified).
        open_questions: Questions that need answering.
        decisions: Decisions made during execution.
        actions_taken: Actions performed (tool calls, etc.).
        results: Results of actions taken.
        created_at: ISO timestamp of creation.
        updated_at: ISO timestamp of last update.
        status: "active", "completed", "failed".
    """
    objective: str = ""
    constraints: List[str] = field(default_factory=list)
    facts: List[str] = field(default_factory=list)
    assumptions: List[str] = field(default_factory=list)
    open_questions: List[str] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)
    actions_taken: List[str] = field(default_factory=list)
    results: List[str] = field(default_factory=list)
    id: str = ""
    created_at: str = ""
    updated_at: str = ""
    status: str = "active"

    def __post_init__(self):
        if not self.id:
            self.id = uuid.uuid4().hex[:16]
        now = datetime.now().isoformat()
        if not self.created_at:
            self.created_at = now
        self.updated_at = now

    def add_fact(self, fact: str):
        """Add a discovered fact."""
        self.facts.append(fact)
        self.updated_at = datetime.now().isoformat()

    def add_assumption(self, assumption: str):
        """Add a working assumption."""
        self.assumptions.append(assumption)
        self.updated_at = datetime.now().isoformat()

    def add_open_question(self, question: str):
        """Add an open question."""
        self.open_questions.append(question)
        self.updated_at = datetime.now().isoformat()

    def add_decision(self, decision: str):
        """Record a decision made."""
        self.decisions.append(decision)
        self.updated_at = datetime.now().isoformat()

    def add_action(self, action: str):
        """Record an action taken."""
        self.actions_taken.append(action)
        self.updated_at = datetime.now().isoformat()

    def add_result(self, result: str):
        """Record a result."""
        self.results.append(result)
        self.updated_at = datetime.now().isoformat()

    def add_constraint(self, constraint: str):
        """Add a constraint."""
        self.constraints.append(constraint)
        self.updated_at = datetime.now().isoformat()

    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dict."""
        return asdict(self)

    def to_context_string(self) -> str:
        """Format as a concise context string for LLM injection."""
        parts = [f"OBJECTIVE: {self.objective}"]
        if self.constraints:
            parts.append("CONSTRAINTS: " + "; ".join(self.constraints[:5]))
        if self.facts:
            parts.append("FACTS: " + "; ".join(self.facts[-5:]))
        if self.assumptions:
            parts.append("ASSUMPTIONS: " + "; ".join(self.assumptions[-3:]))
        if self.open_questions:
            parts.append("OPEN QUESTIONS: " + "; ".join(self.open_questions[-3:]))
        if self.decisions:
            parts.append("DECISIONS: " + "; ".join(self.decisions[-3:]))
        if self.actions_taken:
            parts.append("ACTIONS: " + "; ".join(self.actions_taken[-5:]))
        if self.results:
            parts.append("RESULTS: " + "; ".join(self.results[-3:]))
        return "\n".join(parts)

    def suggest_long_term_writes(self) -> List[Dict[str, str]]:
        """Suggest what should be written to long-term memory.

        Returns a list of {key, value, category} dicts for deliberate
        write-back. This is NOT automatic — the caller decides what to persist.
        """
        suggestions = []

        # Facts discovered during the task
        for fact in self.facts:
            if len(fact) > 10:  # Skip trivial facts
                suggestions.append({
                    "key": f"task_fact:{fact[:50]}",
                    "value": fact,
                    "category": "auto_fact",
                })

        # Decisions made (worth remembering for similar future tasks)
        for decision in self.decisions:
            if len(decision) > 10:
                suggestions.append({
                    "key": f"task_decision:{decision[:50]}",
                    "value": decision,
                    "category": "task",
                })

        # Lessons from failures
        for result in self.results:
            if "fail" in result.lower() or "error" in result.lower():
                suggestions.append({
                    "key": f"task_lesson:{result[:50]}",
                    "value": result,
                    "category": "task",
                })

        return suggestions[:10]  # Cap at 10 writes per task


# ── Persistence Layer ─────────────────────────────────────

_SCRATCHPAD_SCHEMA = """
CREATE TABLE IF NOT EXISTS scratchpads (
    id TEXT PRIMARY KEY,
    objective TEXT NOT NULL,
    data TEXT NOT NULL,
    status TEXT DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_scratchpads_status ON scratchpads(status);
"""


class ScratchpadStore:
    """Persistent storage for scratchpads. One row per task, crash-safe."""

    def __init__(self, db_path: Optional[Path] = None):
        self._db_path = db_path or DATA_DIR / "nally_memory.db"

    def _create_connection(self):
        if TURSO_URL and TURSO_TOKEN:
            try:
                import libsql_experimental as libsql
                from ..memory.store import LibSQLConnectionProxy
                raw = libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN)
                return LibSQLConnectionProxy(raw)
            except ImportError:
                pass
        conn = sqlite3.connect(str(self._db_path), timeout=10.0)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _ensure_schema(self, conn: sqlite3.Connection):
        """Create scratchpads table if it doesn't exist."""
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS scratchpads ("
                "id TEXT PRIMARY KEY, objective TEXT NOT NULL, data TEXT NOT NULL, "
                "status TEXT DEFAULT 'active', created_at TEXT NOT NULL, updated_at TEXT NOT NULL"
                ")"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_scratchpads_status ON scratchpads(status)")
            conn.commit()
        except Exception as e:
            logger.warning(f"Scratchpad schema init failed: {e}")

    def save(self, scratchpad: Scratchpad) -> None:
        """Persist a scratchpad (upsert)."""
        conn = self._create_connection()
        try:
            self._ensure_schema(conn)
            conn.execute(
                "INSERT OR REPLACE INTO scratchpads (id, objective, data, status, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    scratchpad.id,
                    scratchpad.objective,
                    json.dumps(scratchpad.to_dict(), ensure_ascii=False),
                    scratchpad.status,
                    scratchpad.created_at,
                    scratchpad.updated_at,
                ),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Scratchpad save failed: {e}")
        finally:
            conn.close()

    def load(self, scratchpad_id: str) -> Optional[Scratchpad]:
        """Load a scratchpad by ID."""
        conn = self._create_connection()
        try:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT data, status FROM scratchpads WHERE id = ?", (scratchpad_id,)
            ).fetchone()
            if row:
                data = json.loads(row[0])
                # Override status from the DB column (source of truth)
                data["status"] = row[1]
                return Scratchpad(**data)
        except Exception as e:
            logger.error(f"Scratchpad load failed: {e}")
        finally:
            conn.close()
        return None

    def load_active(self, thread_id: str) -> Optional[Scratchpad]:
        """Load the active scratchpad for a thread (if any)."""
        conn = self._create_connection()
        try:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT data FROM scratchpads WHERE status = 'active' ORDER BY updated_at DESC LIMIT 1"
            ).fetchone()
            if row:
                data = json.loads(row[0])
                return Scratchpad(**data)
        except Exception as e:
            logger.error(f"Scratchpad load_active failed: {e}")
        finally:
            conn.close()
        return None

    def complete(self, scratchpad_id: str) -> None:
        """Mark a scratchpad as completed."""
        conn = self._create_connection()
        try:
            self._ensure_schema(conn)
            conn.execute(
                "UPDATE scratchpads SET status = 'completed', updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), scratchpad_id),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Scratchpad complete failed: {e}")
        finally:
            conn.close()

    def fail(self, scratchpad_id: str) -> None:
        """Mark a scratchpad as failed."""
        conn = self._create_connection()
        try:
            self._ensure_schema(conn)
            conn.execute(
                "UPDATE scratchpads SET status = 'failed', updated_at = ? WHERE id = ?",
                (datetime.now().isoformat(), scratchpad_id),
            )
            conn.commit()
        except Exception as e:
            logger.error(f"Scratchpad fail failed: {e}")
        finally:
            conn.close()

    def cleanup(self, max_age_hours: int = 24) -> int:
        """Delete old completed/failed scratchpads. Returns count deleted."""
        conn = self._create_connection()
        try:
            self._ensure_schema(conn)
            cutoff = datetime.now().isoformat()
            cursor = conn.execute(
                "DELETE FROM scratchpads WHERE status IN ('completed', 'failed')",
            )
            conn.commit()
            return cursor.rowcount
        except Exception as e:
            logger.error(f"Scratchpad cleanup failed: {e}")
            return 0
        finally:
            conn.close()

    def get_active_count(self) -> int:
        """Count active scratchpads."""
        conn = self._create_connection()
        try:
            self._ensure_schema(conn)
            row = conn.execute(
                "SELECT COUNT(*) FROM scratchpads WHERE status = 'active'"
            ).fetchone()
            return row[0] if row else 0
        except Exception:
            return 0
        finally:
            conn.close()


# ── Module Singleton ──────────────────────────────────────

scratchpad_store = ScratchpadStore()
