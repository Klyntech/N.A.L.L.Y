"""Suite P task schema — test-side only, no production imports.

A planning task is a GOAL plus a dependency structure, not a prose prompt:
  Goal -> required subgoals -> dependency ordering -> execution -> terminal state

Task types: generation | optimal | verification | execution | replan | reuse
Plan quality is NEVER "did it write a plan": only executed states and
validator verdicts score. Obfuscated twins (obfuscation_of set) share the
exact structured semantics with different surface presentation.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

TASK_TYPES = ("generation", "optimal", "verification", "execution", "replan", "reuse")
PREDICATE_KEYS = ("exists", "contains", "absent", "dir_exists")
REQUIRED_TOP_LEVEL = ("id", "type", "title", "initial_state", "goal", "gold")


@dataclass
class Subgoal:
    id: str
    after: List[str] = field(default_factory=list)
    predicate: Dict[str, Any] = field(default_factory=dict)
    weight: float = 1.0


@dataclass
class TaskSpec:
    id: str
    type: str
    title: str
    presentation: str = ""
    actions: List[str] = field(default_factory=list)
    costs: Dict[str, float] = field(default_factory=dict)
    initial_state: Dict[str, Any] = field(default_factory=dict)
    goal: List[Dict[str, Any]] = field(default_factory=list)
    subgoals: List[Subgoal] = field(default_factory=list)
    candidate_plan: List[Dict[str, Any]] = field(default_factory=list)
    example_plan: List[Dict[str, Any]] = field(default_factory=list)
    start_and_actions: Dict[str, Any] = field(default_factory=dict)
    prefix_executed: List[Dict[str, Any]] = field(default_factory=list)
    unexpected_change: Dict[str, Any] = field(default_factory=dict)
    gold: Dict[str, Any] = field(default_factory=dict)
    obfuscation_of: Optional[str] = None
    seed: int = 0

    def validate(self, known_ids: List[str]) -> List[str]:
        errors = []
        if self.type not in TASK_TYPES:
            errors.append(f"{self.id}: bad type {self.type!r}")
        for pred in self.goal:
            if len(pred) != 1 or next(iter(pred)) not in PREDICATE_KEYS:
                errors.append(f"{self.id}: bad goal predicate {pred!r}")
        sids = [s.id for s in self.subgoals]
        if len(sids) != len(set(sids)):
            errors.append(f"{self.id}: duplicate subgoal ids")
        for s in self.subgoals:
            if len(s.predicate) != 1 or next(iter(s.predicate)) not in PREDICATE_KEYS:
                errors.append(f"{self.id}:{s.id}: bad predicate {s.predicate!r}")
            for dep in s.after:
                if dep not in sids:
                    errors.append(f"{self.id}:{s.id}: 'after' refs unknown {dep!r}")
        if self.type == "verification" and not self.candidate_plan:
            errors.append(f"{self.id}: verification needs candidate_plan")
        if self.type == "reuse" and not self.example_plan:
            errors.append(f"{self.id}: reuse needs example_plan")
        if self.type == "execution" and not self.start_and_actions:
            errors.append(f"{self.id}: execution needs start_and_actions")
        if self.type == "replan" and not self.unexpected_change:
            errors.append(f"{self.id}: replan needs unexpected_change")
        if self.obfuscation_of and self.obfuscation_of not in known_ids:
            errors.append(f"{self.id}: obfuscation_of unknown {self.obfuscation_of!r}")
        if not self.gold:
            errors.append(f"{self.id}: missing gold")
        return errors


def task_from_dict(data: Dict[str, Any]) -> TaskSpec:
    missing = [k for k in REQUIRED_TOP_LEVEL if k not in data]
    if missing:
        raise ValueError(f"task {data.get('id', '?')}: missing keys {missing}")
    return TaskSpec(
        id=data["id"],
        type=data["type"],
        title=data.get("title", ""),
        presentation=data.get("presentation", ""),
        actions=list(data.get("actions", ["create_dir", "write_file", "move_file", "delete_file"])),
        costs=dict(data.get("costs", {})),
        initial_state=dict(data["initial_state"]),
        goal=list(data["goal"]),
        subgoals=[Subgoal(id=s["id"], after=list(s.get("after", [])),
                          predicate=dict(s["predicate"]),
                          weight=float(s.get("weight", 1.0)))
                  for s in data.get("subgoals", [])],
        candidate_plan=list(data.get("candidate_plan", [])),
        example_plan=list(data.get("example_plan", [])),
        start_and_actions=dict(data.get("start_and_actions", {})),
        prefix_executed=list(data.get("prefix_executed", [])),
        unexpected_change=dict(data.get("unexpected_change", {})),
        gold=dict(data.get("gold", {})),
        obfuscation_of=data.get("obfuscation_of"),
        seed=int(data.get("seed", 0)),
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
