"""Suite U — Computer-use benchmark schema.

Tasks exercise NALLY as a computer-using agent via process():
objective → plan/react → NallPuter operations → observe → verify → complete.

Each task declares:
  - objective: natural language user request
  - verify: list of file/content checks after completion
  - budget: max seconds for the task
  - intent: expected classification (SIMPLE/COMPLEX)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class VerifyCheck:
    """A post-completion verification check."""
    kind: str  # file_exists | file_contains | file_line_count
    path: str
    expected: Any = None  # content string, line count int, etc.

    def validate(self) -> List[str]:
        errors = []
        if self.kind not in ("file_exists", "file_contains", "file_line_count"):
            errors.append(f"bad verify kind: {self.kind}")
        if not self.path:
            errors.append("verify path required")
        return errors


@dataclass
class ComputerTask:
    id: str
    objective: str
    verify: List[VerifyCheck]
    budget_sec: int = 120
    intent: str = "SIMPLE"  # SIMPLE | COMPLEX
    description: str = ""
    category: str = ""  # stc | mtc | mcp | plan | persist | recovery | budget

    def validate(self) -> List[str]:
        errors = []
        if not self.id:
            errors.append("task id required")
        if not self.objective:
            errors.append("objective required")
        for v in self.verify:
            errors.extend(v.validate())
        return errors

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "objective": self.objective,
            "budget_sec": self.budget_sec,
            "intent": self.intent,
            "description": self.description,
            "category": self.category,
            "verify": [{"kind": v.kind, "path": v.path, "expected": v.expected} for v in self.verify],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> ComputerTask:
        return cls(
            id=d["id"],
            objective=d["objective"],
            budget_sec=d.get("budget_sec", 120),
            intent=d.get("intent", "SIMPLE"),
            description=d.get("description", ""),
            category=d.get("category", ""),
            verify=[VerifyCheck(**v) for v in d.get("verify", [])],
        )


@dataclass
class TaskResult:
    task_id: str
    passed: bool
    response: str
    verify_results: Dict[str, bool]  # check_label → pass/fail
    wall_ms: int
    tool_calls: int
    budget_used_pct: float
    intent_class: str = ""
    error: str = ""
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "passed": self.passed,
            "response": self.response[:500],
            "verify_results": self.verify_results,
            "wall_ms": self.wall_ms,
            "tool_calls": self.tool_calls,
            "budget_used_pct": round(self.budget_used_pct, 1),
            "intent_class": self.intent_class,
            "error": self.error,
            "timestamp": self.timestamp,
        }


def load_tasks(json_path: Optional[str] = None) -> List[ComputerTask]:
    """Load tasks from the bundled JSON file."""
    if json_path is None:
        json_path = str(Path(__file__).parent / "tasks.json")
    with open(json_path) as f:
        data = json.load(f)
    tasks = [ComputerTask.from_dict(d) for d in data["tasks"]]
    for t in tasks:
        errs = t.validate()
        if errs:
            raise ValueError(f"Task {t.id}: {errs}")
    return tasks
