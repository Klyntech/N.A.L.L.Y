"""Task State Persistence — Save and resume multi-step work.

When Nally is working on a multi-file task (building a landing page, creating
a project, etc.) and gets interrupted, she currently re-reads ALL files from
scratch. This module saves task progress after each action so she can resume
exactly where she stopped.

Storage: SQLite (data/task_state.db)
"""

import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import DATA_DIR
from ..utils.logger import logger

def _get_db() -> sqlite3.Connection:
    """Get a database connection for task state."""
    db_path = DATA_DIR / "task_state.db"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), timeout=10.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_table():
    """Create the task_states table if it doesn't exist."""
    try:
        conn = _get_db()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_states (
                session_id TEXT PRIMARY KEY,
                task_description TEXT NOT NULL,
                status TEXT DEFAULT 'in_progress',
                completed_steps TEXT DEFAULT '[]',
                pending_steps TEXT DEFAULT '[]',
                files_created TEXT DEFAULT '[]',
                files_modified TEXT DEFAULT '[]',
                key_decisions TEXT DEFAULT '[]',
                current_step TEXT DEFAULT '',
                last_tool_call TEXT DEFAULT '',
                last_tool_result TEXT DEFAULT '',
                context_summary TEXT DEFAULT '',
                started_at REAL,
                updated_at REAL,
                completed_at REAL
            )
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_task_status ON task_states(status)
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Failed to create task_states table: {e}")


# Initialize on import
_ensure_table()


class TaskState:
    """Represents the state of a multi-step task being worked on."""

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.task_description: str = ""
        self.status: str = "in_progress"
        self.completed_steps: List[str] = []
        self.pending_steps: List[str] = []
        self.files_created: List[str] = []
        self.files_modified: List[str] = []
        self.key_decisions: List[str] = []
        self.current_step: str = ""
        self.last_tool_call: str = ""
        self.last_tool_result: str = ""
        self.context_summary: str = ""
        self.started_at: float = 0
        self.updated_at: float = 0
        self.completed_at: float = 0

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "task_description": self.task_description,
            "status": self.status,
            "completed_steps": self.completed_steps,
            "pending_steps": self.pending_steps,
            "files_created": self.files_created,
            "files_modified": self.files_modified,
            "key_decisions": self.key_decisions,
            "current_step": self.current_step,
            "last_tool_call": self.last_tool_call,
            "last_tool_result": self.last_tool_result,
            "context_summary": self.context_summary,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TaskState":
        state = cls(data.get("session_id", ""))
        state.task_description = data.get("task_description", "")
        state.status = data.get("status", "in_progress")
        state.completed_steps = data.get("completed_steps", [])
        state.pending_steps = data.get("pending_steps", [])
        state.files_created = data.get("files_created", [])
        state.files_modified = data.get("files_modified", [])
        state.key_decisions = data.get("key_decisions", [])
        state.current_step = data.get("current_step", "")
        state.last_tool_call = data.get("last_tool_call", "")
        state.last_tool_result = data.get("last_tool_result", "")
        state.context_summary = data.get("context_summary", "")
        state.started_at = data.get("started_at", 0)
        state.updated_at = data.get("updated_at", 0)
        state.completed_at = data.get("completed_at", 0)
        return state


class TaskStateManager:
    """Manages task state persistence. Thread-safe singleton."""

    def __init__(self):
        self._lock = threading.Lock()

    def get(self, session_id: str) -> Optional[TaskState]:
        """Get the current task state for a session."""
        try:
            conn = _get_db()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM task_states WHERE session_id = ?",
                (session_id,)
            )
            row = cursor.fetchone()
            conn.close()

            if not row:
                return None

            data = dict(row)
            # Parse JSON fields
            for field in ["completed_steps", "pending_steps", "files_created",
                          "files_modified", "key_decisions"]:
                if isinstance(data.get(field), str):
                    try:
                        data[field] = json.loads(data[field])
                    except json.JSONDecodeError:
                        data[field] = []

            return TaskState.from_dict(data)

        except Exception as e:
            logger.warning(f"Failed to get task state for {session_id}: {e}")
            return None

    def save(self, state: TaskState):
        """Save or update a task state."""
        try:
            conn = _get_db()
            now = time.time()
            if not state.started_at:
                state.started_at = now
            state.updated_at = now

            conn.execute("""
                INSERT OR REPLACE INTO task_states
                (session_id, task_description, status, completed_steps, pending_steps,
                 files_created, files_modified, key_decisions, current_step,
                 last_tool_call, last_tool_result, context_summary,
                 started_at, updated_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                state.session_id,
                state.task_description,
                state.status,
                json.dumps(state.completed_steps),
                json.dumps(state.pending_steps),
                json.dumps(state.files_created),
                json.dumps(state.files_modified),
                json.dumps(state.key_decisions),
                state.current_step,
                state.last_tool_call,
                state.last_tool_result,
                state.context_summary,
                state.started_at,
                state.updated_at,
                state.completed_at,
            ))
            conn.commit()
            conn.close()

        except Exception as e:
            logger.warning(f"Failed to save task state: {e}")

    def delete(self, session_id: str):
        """Delete a task state (after task completion)."""
        try:
            conn = _get_db()
            conn.execute("DELETE FROM task_states WHERE session_id = ?", (session_id,))
            conn.commit()
            conn.close()
        except Exception as e:
            logger.warning(f"Failed to delete task state: {e}")

    def list_active(self) -> List[TaskState]:
        """List all active (in-progress) tasks."""
        try:
            conn = _get_db()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM task_states WHERE status = 'in_progress' ORDER BY updated_at DESC"
            )
            rows = cursor.fetchall()
            conn.close()

            states = []
            for row in rows:
                data = dict(row)
                for field in ["completed_steps", "pending_steps", "files_created",
                              "files_modified", "key_decisions"]:
                    if isinstance(data.get(field), str):
                        try:
                            data[field] = json.loads(data[field])
                        except json.JSONDecodeError:
                            data[field] = []
                states.append(TaskState.from_dict(data))

            return states

        except Exception as e:
            logger.warning(f"Failed to list active tasks: {e}")
            return []

    def format_for_prompt(self, state: TaskState) -> str:
        """Format a task state as context for the LLM to resume."""
        if not state:
            return ""

        lines = []
        lines.append("=== TASK RESUME CONTEXT ===")
        lines.append(f"Task: {state.task_description}")
        lines.append(f"Status: {state.status}")
        lines.append("")

        if state.completed_steps:
            lines.append("COMPLETED:")
            for step in state.completed_steps:
                lines.append(f"  [x] {step}")
            lines.append("")

        if state.pending_steps:
            lines.append("PENDING:")
            for step in state.pending_steps:
                lines.append(f"  [ ] {step}")
            lines.append("")

        if state.files_created:
            lines.append("FILES CREATED:")
            for f in state.files_created:
                lines.append(f"  - {f}")
            lines.append("")

        if state.files_modified:
            lines.append("FILES MODIFIED:")
            for f in state.files_modified:
                lines.append(f"  - {f}")
            lines.append("")

        if state.key_decisions:
            lines.append("KEY DECISIONS:")
            for d in state.key_decisions:
                lines.append(f"  - {d}")
            lines.append("")

        if state.current_step:
            lines.append(f"CURRENT STEP: {state.current_step}")
            lines.append("")

        if state.context_summary:
            lines.append(f"SUMMARY: {state.context_summary}")
            lines.append("")

        lines.append("=== RESUME INSTRUCTIONS ===")
        lines.append("Continue from where you left off. Do NOT re-read files already created.")
        lines.append("Read only the files listed above if you need to reference them.")
        lines.append("Pick up at the current step and continue with the pending steps.")

        return "\n".join(lines)


# Singleton
task_state_manager = TaskStateManager()

