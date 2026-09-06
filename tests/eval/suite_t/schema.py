"""Suite T task schema — test-side only, no production imports.

Every task JSON must define:
  initial_state -> dependency_graph -> intermediate milestone(s)
  -> valid terminal state -> invalid/minefield states -> scoring rule.

The scorer grades STATE TRANSITIONS and OUTCOMES (milestone DAG +
world snapshots), never final-sentence plausibility.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

MATCH_MODES = ("exact", "loose", "exists")
MILESTONE_KINDS = ("tool_call", "world_state")
REQUIRED_TOP_LEVEL = (
    "id", "category", "initial_user_message", "initial_state",
    "available_tools", "dependency_graph", "milestones",
    "terminal_state", "scoring",
)
VALID_CATEGORIES = ("STC", "MTC", "MUT", "SD", "C", "II")


@dataclass
class Milestone:
    id: str
    kind: str  # tool_call | world_state
    after: List[str] = field(default_factory=list)
    # tool_call fields
    tool: Optional[str] = None
    args: Dict[str, Any] = field(default_factory=dict)
    arg_match: str = "exact"  # exact | loose
    # world_state fields
    path: Optional[str] = None  # dotted path into snapshot, e.g. "messages[-1].text"
    expected: Any = None
    match: str = "exact"  # exact | loose | exists
    weight: float = 1.0

    def validate(self, task_id: str) -> List[str]:
        errors = []
        if self.kind not in MILESTONE_KINDS:
            errors.append(f"{task_id}:{self.id}: bad kind {self.kind!r}")
        if self.kind == "tool_call" and not self.tool:
            errors.append(f"{task_id}:{self.id}: tool_call needs 'tool'")
        if self.kind == "world_state" and not self.path:
            errors.append(f"{task_id}:{self.id}: world_state needs 'path'")
        if self.arg_match not in ("exact", "loose"):
            errors.append(f"{task_id}:{self.id}: bad arg_match {self.arg_match!r}")
        if self.match not in MATCH_MODES:
            errors.append(f"{task_id}:{self.id}: bad match {self.match!r}")
        return errors


@dataclass
class TaskSpec:
    id: str
    category: str
    initial_user_message: str
    initial_state: Dict[str, Any]
    available_tools: List[str]
    dependency_graph: Dict[str, List[str]]  # tool -> tools it depends on
    milestones: List[Milestone]
    minefields: List[Milestone]
    terminal_state: Dict[str, Any]
    user_turns: List[Dict[str, Any]]
    gold_tool_sequence: List[Dict[str, Any]]
    seed: int = 0
    scoring: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> List[str]:
        errors = []
        if self.category not in VALID_CATEGORIES:
            errors.append(f"{self.id}: bad category {self.category!r}")
        mids = [m.id for m in self.milestones]
        if len(mids) != len(set(mids)):
            errors.append(f"{self.id}: duplicate milestone ids")
        if self.category in ("MTC", "SD") and len(self.milestones) < 2:
            errors.append(f"{self.id}: {self.category} needs >=2 milestones")
        for m in self.milestones + self.minefields:
            errors.extend(m.validate(self.id))
            for dep in m.after:
                if dep not in mids:
                    errors.append(f"{self.id}:{m.id}: 'after' refs unknown {dep!r}")
        if self._has_cycle(mids):
            errors.append(f"{self.id}: milestone 'after' graph has a cycle")
        if not self.gold_tool_sequence:
            errors.append(f"{self.id}: missing gold_tool_sequence")
        if self.category == "II" and not self.minefields:
            errors.append(f"{self.id}: II tasks require >=1 minefield")
        return errors

    def _has_cycle(self, mids: List[str]) -> bool:
        order = {mid: i for i, mid in enumerate(mids)}
        adjacent = {m.id: [d for d in m.after] for m in self.milestones}
        visiting, done = set(), set()

        def visit(node: str) -> bool:
            if node in done:
                return False
            if node in visiting:
                return True
            visiting.add(node)
            for dep in adjacent.get(node, []):
                if visit(dep):
                    return True
            visiting.discard(node)
            done.add(node)
            return False

        return any(visit(mid) for mid in mids)


def _milestone_from_dict(data: Dict[str, Any]) -> Milestone:
    return Milestone(
        id=data["id"],
        kind=data["kind"],
        after=list(data.get("after", [])),
        tool=data.get("tool"),
        args=dict(data.get("args", {})),
        arg_match=data.get("arg_match", "exact"),
        path=data.get("path"),
        expected=data.get("expected"),
        match=data.get("match", "exact"),
        weight=float(data.get("weight", 1.0)),
    )


def task_from_dict(data: Dict[str, Any]) -> TaskSpec:
    missing = [k for k in REQUIRED_TOP_LEVEL if k not in data]
    if missing:
        raise ValueError(f"task {data.get('id', '?')}: missing keys {missing}")
    return TaskSpec(
        id=data["id"],
        category=data["category"],
        initial_user_message=data["initial_user_message"],
        initial_state=dict(data["initial_state"]),
        available_tools=list(data["available_tools"]),
        dependency_graph={k: list(v) for k, v in data["dependency_graph"].items()},
        milestones=[_milestone_from_dict(m) for m in data["milestones"]],
        minefields=[_milestone_from_dict(m) for m in data.get("minefields", [])],
        terminal_state=dict(data["terminal_state"]),
        user_turns=list(data.get("user_turns", [])),
        gold_tool_sequence=list(data.get("gold_tool_sequence", [])),
        seed=int(data.get("seed", 0)),
        scoring=dict(data.get("scoring", {})),
    )


def load_task(path: Path) -> TaskSpec:
    with open(path, encoding="utf-8") as f:
        return task_from_dict(json.load(f))


def load_all_tasks(tasks_dir: Optional[Path] = None) -> List[TaskSpec]:
    if tasks_dir is None:
        tasks_dir = Path(__file__).parent / "tasks"
    tasks = []
    for json_file in sorted(Path(tasks_dir).glob("*.json")):
        tasks.append(load_task(json_file))
    return tasks
