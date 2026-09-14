"""Workflow checkpoint store — durable runs for NALLY workflows.

Uses the same SQLite DB as memory (nally_memory.db) via MemoryRepository.
Table workflow_runs already in _SCHEMA (memories_vec + workflow_runs).
"""

import json
import time
import uuid
from typing import Dict, List, Optional

from ..utils.logger import logger


def _now() -> str:
    import datetime

    return datetime.datetime.now().isoformat()


class WorkflowStore:
    """Persist workflow runs — status, inputs, outputs, visited."""

    def save(self, run_id: str, workflow_name: str, status: str, inputs: Dict, outputs: Dict, visited: List[str]):
        try:
            from ..memory import memory_store

            now = _now()
            with memory_store._connection() as conn:
                # Upsert
                existing = conn.execute("SELECT id FROM workflow_runs WHERE id = ?", (run_id,)).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE workflow_runs SET workflow_name=?, status=?, inputs_json=?, outputs_json=?, visited_json=?, updated=? WHERE id=?",
                        (workflow_name, status, json.dumps(inputs), json.dumps(outputs), json.dumps(visited), now, run_id),
                    )
                else:
                    conn.execute(
                        "INSERT INTO workflow_runs (id, workflow_name, status, inputs_json, outputs_json, visited_json, created, updated) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                        (run_id, workflow_name, status, json.dumps(inputs), json.dumps(outputs), json.dumps(visited), now, now),
                    )
        except Exception as e:
            logger.debug(f"workflow store save failed: {e}")

    def get(self, run_id: str) -> Optional[Dict]:
        try:
            from ..memory import memory_store

            with memory_store._connection() as conn:
                row = conn.execute("SELECT * FROM workflow_runs WHERE id = ?", (run_id,)).fetchone()
                if not row:
                    return None
                return {
                    "id": row["id"],
                    "workflow_name": row["workflow_name"],
                    "status": row["status"],
                    "inputs": json.loads(row["inputs_json"] or "{}"),
                    "outputs": json.loads(row["outputs_json"] or "{}"),
                    "visited": json.loads(row["visited_json"] or "[]"),
                    "created": row["created"],
                    "updated": row["updated"],
                }
        except Exception as e:
            logger.debug(f"workflow store get failed: {e}")
            return None

    def list_recent(self, limit: int = 20) -> List[Dict]:
        try:
            from ..memory import memory_store

            with memory_store._connection() as conn:
                rows = conn.execute("SELECT * FROM workflow_runs ORDER BY updated DESC LIMIT ?", (limit,)).fetchall()
                out = []
                for r in rows:
                    out.append(
                        {
                            "id": r["id"],
                            "workflow_name": r["workflow_name"],
                            "status": r["status"],
                            "updated": r["updated"],
                        }
                    )
                return out
        except Exception:
            return []

    def new_id(self) -> str:
        return uuid.uuid4().hex[:12]


workflow_store = WorkflowStore()
