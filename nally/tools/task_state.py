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
from .registry import Tool


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


# ── Tool class ──────────────────────────────────────────

class TaskStateTool(Tool):
    """Save and resume multi-step task progress.

    When working on a multi-file project (building a page, creating files, etc.),
    use this tool to save your progress after each major step. If interrupted,
    Nally can read the saved state and resume without re-reading everything.
    """

    def __init__(self):
        super().__init__(
            name="task_state",
            description=(
                "Save and resume multi-step task progress. "
                "Use 'save' to record what you've done and what's left. "
                "Use 'resume' to get a summary of where you left off. "
                "Use 'complete' to mark a task as done and clean up. "
                "Use 'list' to see all active tasks."
            ),
            permission="safe",
            parameters={
                "action": {
                    "type": "string",
                    "description": "Action: save, resume, complete, list",
                    "required": True,
                    "enum": ["save", "resume", "complete", "list"],
                },
                "task_description": {
                    "type": "string",
                    "description": "Description of the task (required for save)",
                },
                "completed_steps": {
                    "type": "string",
                    "description": "Comma-separated list of completed steps (for save)",
                },
                "pending_steps": {
                    "type": "string",
                    "description": "Comma-separated list of pending steps (for save)",
                },
                "files_created": {
                    "type": "string",
                    "description": "Comma-separated list of files created (for save)",
                },
                "files_modified": {
                    "type": "string",
                    "description": "Comma-separated list of files modified (for save)",
                },
                "key_decisions": {
                    "type": "string",
                    "description": "Comma-separated list of key decisions made (for save)",
                },
                "current_step": {
                    "type": "string",
                    "description": "What you're currently working on (for save)",
                },
                "context_summary": {
                    "type": "string",
                    "description": "Brief summary of progress so far (for save)",
                },
            },
        )

    def execute(
        self,
        action: str,
        task_description: str = "",
        completed_steps: str = "",
        pending_steps: str = "",
        files_created: str = "",
        files_modified: str = "",
        key_decisions: str = "",
        current_step: str = "",
        context_summary: str = "",
    ) -> str:
        from ..config import SESSION_ID

        session_id = SESSION_ID

        if action == "list":
            states = task_state_manager.list_active()
            if not states:
                return "No active tasks."
            lines = [f"=== ACTIVE TASKS ({len(states)}) ==="]
            for s in states:
                elapsed = time.time() - s.started_at if s.started_at else 0
                mins = int(elapsed // 60)
                lines.append(f"\n[{s.session_id}] {s.task_description[:80]}")
                lines.append(f"  Status: {s.status} | Step: {s.current_step or 'N/A'}")
                lines.append(f"  Completed: {len(s.completed_steps)} | Pending: {len(s.pending_steps)} | Files: {len(s.files_created) + len(s.files_modified)}")
                lines.append(f"  Elapsed: {mins}m")
            return "\n".join(lines)

        if action == "complete":
            state = task_state_manager.get(session_id)
            if state:
                state.status = "completed"
                state.completed_at = time.time()
                task_state_manager.save(state)
                task_state_manager.delete(session_id)
                return f"Task completed and cleaned up: {state.task_description[:60]}"
            return "No active task found to complete."

        if action == "resume":
            state = task_state_manager.get(session_id)
            if not state:
                # Check for any active tasks
                states = task_state_manager.list_active()
                if states:
                    lines = ["No task saved for this session, but found active tasks:"]
                    for s in states:
                        lines.append(f"  [{s.session_id}] {s.task_description[:60]}")
                    lines.append("\nTell me which task to resume, or start fresh.")
                    return "\n".join(lines)
                return "No saved task to resume. Starting fresh."
            return task_state_manager.format_for_prompt(state)

        if action == "save":
            if not task_description:
                return "Error: task_description is required for save."

            state = task_state_manager.get(session_id)
            if not state:
                state = TaskState(session_id)

            state.task_description = task_description
            state.status = "in_progress"

            if completed_steps:
                state.completed_steps = [s.strip() for s in completed_steps.split(",") if s.strip()]
            if pending_steps:
                state.pending_steps = [s.strip() for s in pending_steps.split(",") if s.strip()]
            if files_created:
                state.files_created = [f.strip() for f in files_created.split(",") if f.strip()]
            if files_modified:
                state.files_modified = [f.strip() for f in files_modified.split(",") if f.strip()]
            if key_decisions:
                state.key_decisions = [d.strip() for d in key_decisions.split(",") if d.strip()]
            if current_step:
                state.current_step = current_step
            if context_summary:
                state.context_summary = context_summary

            # Track the last tool call
            state.last_tool_call = current_step or state.last_tool_call

            task_state_manager.save(state)
            return f"Task state saved. Completed: {len(state.completed_steps)} | Pending: {len(state.pending_steps)} | Files: {len(state.files_created) + len(state.files_modified)}"

        return f"Unknown action: {action}. Use save, resume, complete, or list."
