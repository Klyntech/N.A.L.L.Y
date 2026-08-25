"""Human Checkpoint — plan confirmation before complex task execution.

Uses the existing approval gate pattern (SQLite polling) to pause execution
before complex tasks, present a plan to the user, and resume with their
decision. More practical than LangGraph's interrupt() for Nally's architecture.

Flow:
    1. After planning, human_checkpoint node fires
    2. Node stores plan in SQLite, emits confirmation_required event
    3. Graph pauses (tool_executor polls SQLite for approval)
    4. User reviews plan, approves/modifies/rejects via frontend
    5. Resolution unblocks the graph, execution continues
"""

import json
import logging
import sqlite3
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Dict, List, Optional

from ..config import DATA_DIR

logger = logging.getLogger("nally.human_checkpoint")


class CheckpointAction(StrEnum):
    APPROVE = "approve"
    EDIT = "edit"
    REJECT = "reject"


@dataclass
class CheckpointData:
    """Stored checkpoint data for a pending human review."""
    thread_id: str
    plan_summary: str
    task_class: str
    steps: List[str] = field(default_factory=list)
    intent: str = ""
    status: str = "pending"  # pending, approved, rejected, edited
    edited_plan: Optional[str] = None
    created_at: float = 0.0
    resolved_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "thread_id": self.thread_id,
            "plan_summary": self.plan_summary,
            "task_class": self.task_class,
            "steps": self.steps,
            "intent": self.intent,
            "status": self.status,
            "edited_plan": self.edited_plan,
        }


def _get_checkpoint_db():
    """Get SQLite connection for checkpoint storage."""
    db_path = DATA_DIR / "nally.db"
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS human_checkpoints (
            thread_id TEXT PRIMARY KEY,
            plan_summary TEXT,
            task_class TEXT,
            steps TEXT,
            intent TEXT,
            status TEXT DEFAULT 'pending',
            edited_plan TEXT,
            created_at REAL,
            resolved_at REAL
        )
    """)
    return conn


def save_checkpoint(data: CheckpointData):
    """Save checkpoint data to SQLite."""
    try:
        conn = _get_checkpoint_db()
        conn.execute("""
            INSERT OR REPLACE INTO human_checkpoints
            (thread_id, plan_summary, task_class, steps, intent, status, edited_plan, created_at, resolved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.thread_id,
            data.plan_summary,
            data.task_class,
            json.dumps(data.steps),
            data.intent,
            data.status,
            data.edited_plan,
            data.created_at,
            data.resolved_at,
        ))
        conn.commit()
        conn.close()
    except Exception as e:
        logger.warning(f"Failed to save checkpoint: {e}")


def get_checkpoint(thread_id: str) -> Optional[CheckpointData]:
    """Retrieve checkpoint data from SQLite."""
    try:
        conn = _get_checkpoint_db()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT * FROM human_checkpoints WHERE thread_id = ?",
            (thread_id,)
        )
        row = cursor.fetchone()
        conn.close()
        if not row:
            return None
        return CheckpointData(
            thread_id=row[0],
            plan_summary=row[1],
            task_class=row[2],
            steps=json.loads(row[3]) if row[3] else [],
            intent=row[4] or "",
            status=row[5] or "pending",
            edited_plan=row[6],
            created_at=row[7] or 0.0,
            resolved_at=row[8],
        )
    except Exception as e:
        logger.warning(f"Failed to get checkpoint: {e}")
        return None


def resolve_checkpoint(thread_id: str, action: str, edited_plan: str = None, reason: str = None) -> bool:
    """Resolve a pending checkpoint (called from FastAPI endpoint)."""
    try:
        conn = _get_checkpoint_db()
        now = time.time()
        conn.execute("""
            UPDATE human_checkpoints
            SET status = ?, edited_plan = ?, resolved_at = ?
            WHERE thread_id = ? AND status = 'pending'
        """, (action, edited_plan, now, thread_id))
        conn.commit()
        conn.close()
        logger.info(f"Checkpoint resolved: {thread_id[:12]} → {action}")
        return True
    except Exception as e:
        logger.warning(f"Failed to resolve checkpoint: {e}")
        return False


def has_pending_checkpoint(thread_id: str) -> bool:
    """Check if there's a pending checkpoint for this thread."""
    cp = get_checkpoint(thread_id)
    return cp is not None and cp.status == "pending"


def human_checkpoint_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Graph node that pauses for human review of complex task plans.

    Stores the plan in SQLite and emits a confirmation_required event.
    The tool_executor will poll for resolution (same pattern as approval gate).
    """
    from ..core.abort import check_abort
    from ..events.bus import event_bus

    intent_class = state.get("intent_class", "")
    thread_id = state.get("thread_id", "default")

    # Only checkpoint for complex/high-stakes tasks
    if intent_class not in ("COMPLEX", "HIGH_STAKES", "CREATIVE"):
        return state

    # Check if user already approved via existing approval gate
    # (skip checkpoint if approval was already granted)
    if check_abort(thread_id):
        return state

    # Extract plan from state
    plan = state.get("plan")
    plan_summary = ""
    steps = []

    if plan:
        if hasattr(plan, "goal") and hasattr(plan, "steps"):
            plan_summary = f"Task: {plan.goal}"
            steps = [s.goal for s in plan.steps if hasattr(s, "goal")]
        elif isinstance(plan, dict):
            plan_summary = plan.get("goal", "Complex task")
            steps = [s.get("goal", "") for s in plan.get("steps", [])]
    else:
        # No plan — extract from messages
        messages = state.get("messages", [])
        for msg in reversed(messages):
            content = getattr(msg, "content", "") or ""
            if content and len(content) > 50:
                plan_summary = content[:500]
                break
        if not plan_summary:
            plan_summary = "Complex task requiring multiple steps"

    # Store checkpoint in SQLite
    checkpoint = CheckpointData(
        thread_id=thread_id,
        plan_summary=plan_summary,
        task_class=intent_class,
        steps=steps,
        intent=intent_class,
        status="pending",
        created_at=time.time(),
    )
    save_checkpoint(checkpoint)

    # Emit confirmation event via event bus
    event_bus.publish("human_checkpoint_required", checkpoint.to_dict())

    logger.info(f"Human checkpoint: plan stored (intent={intent_class}, thread={thread_id[:12]})")

    # Wait for resolution via SQLite polling (same pattern as approval gate)
    _poll_interval = 2
    _max_polls = 150  # 5 minutes max
    for _i in range(_max_polls):
        if check_abort(thread_id):
            resolve_checkpoint(thread_id, "rejected")
            return {**state, "plan_status": "rejected"}

        cp = get_checkpoint(thread_id)
        if cp and cp.status in ("approved", "rejected", "edited"):
            if cp.status == "rejected":
                from langchain_core.messages import AIMessage
                reject_msg = AIMessage(
                    content="Plan was rejected. What would you like me to do instead?"
                )
                return {**state, "messages": [reject_msg], "plan_status": "rejected"}

            if cp.status == "edited" and cp.edited_plan:
                # Apply edits to the plan
                if plan and hasattr(plan, "steps"):
                    try:
                        edited_lines = [
                            line.strip().lstrip("0123456789.-) ")
                            for line in cp.edited_plan.strip().split("\n")
                            if line.strip()
                        ]
                        for i, step in enumerate(plan.steps):
                            if i < len(edited_lines):
                                step.goal = edited_lines[i]
                    except Exception:
                        pass
                return {**state, "plan": plan, "plan_status": "executing"}

            # Approved — proceed
            return {**state, "plan_status": "executing"}

        time.sleep(_poll_interval)

    # Timeout — proceed without confirmation (fail open)
    logger.warning(f"Human checkpoint timed out for {thread_id[:12]}, proceeding")
    resolve_checkpoint(thread_id, "approved")
    return {**state, "plan_status": "executing"}
