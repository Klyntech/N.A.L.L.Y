"""Suite P planning world + mechanical validator — test-side only.

File-system planning domain (Blocksworld analogue):
  create_dir {path}            pre: path free, parent exists
  write_file {path, content}   pre: parent dir exists (overwrite allowed)
  move_file  {src, dst}        pre: src file exists, dst parent exists
  delete_file {path}           pre: file exists

The validator (not fluency, not an LLM judge) is ground truth: it simulates
a plan step by step, reports the FIRST failure with its missing precondition,
checks goal conjunction, and prices the plan. BFS gives optimal cost on the
tiny task spaces for the `optimal` type.
"""

from __future__ import annotations

import copy
from collections import deque
from typing import Any, Dict, List, Optional, Tuple

ACTIONS = ("create_dir", "write_file", "move_file", "delete_file")
BFS_STATE_CAP = 5000


def _parent(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else ""


class PWorld:
    def __init__(self, initial_state: Dict[str, Any]):
        self.state: Dict[str, Any] = {
            "dirs": list(initial_state.get("dirs", [])),
            "files": dict(initial_state.get("files", {})),
        }

    def snapshot(self) -> Dict[str, Any]:
        return copy.deepcopy(self.state)

    def check_step(self, step: Dict[str, Any]) -> Optional[str]:
        """Return None if executable, else a missing-precondition description."""
        name, args = step.get("action", ""), step.get("args", {})
        if name not in ACTIONS:
            return f"unknown action {name!r}"
        if name == "create_dir":
            path = args.get("path", "")
            if path in self.state["dirs"] or path in self.state["files"]:
                return f"path {path!r} already exists"
            parent = _parent(path)
            if parent != "" and parent not in self.state["dirs"]:
                return f"parent dir {parent!r} does not exist"
            return None
        if name == "write_file":
            path = args.get("path", "")
            parent = _parent(path)
            if parent != "" and parent not in self.state["dirs"]:
                return f"parent dir {parent!r} does not exist"
            return None
        if name == "move_file":
            src, dst = args.get("src", ""), args.get("dst", "")
            if src not in self.state["files"]:
                return f"source file {src!r} does not exist"
            parent = _parent(dst)
            if parent != "" and parent not in self.state["dirs"]:
                return f"destination parent dir {parent!r} does not exist"
            return None
        if name == "delete_file":
            path = args.get("path", "")
            if path not in self.state["files"]:
                return f"file {path!r} does not exist"
            return None
        return f"unknown action {name!r}"

    def apply_validated(self, step: Dict[str, Any]) -> None:
        name, args = step.get("action", ""), step.get("args", {})
        if name == "create_dir":
            self.state["dirs"].append(args["path"])
        elif name == "write_file":
            self.state["files"][args["path"]] = str(args.get("content", ""))
        elif name == "move_file":
            self.state["files"][args["dst"]] = self.state["files"].pop(args["src"])
        elif name == "delete_file":
            self.state["files"].pop(args["path"], None)


def predicate_holds(state: Dict[str, Any], predicate: Dict[str, Any]) -> bool:
    if "exists" in predicate:
        return predicate["exists"] in state.get("files", {})
    if "contains" in predicate:
        path, text = predicate["contains"]
        return text in state.get("files", {}).get(path, "")
    if "absent" in predicate:
        path = predicate["absent"]
        return path not in state.get("files", {}) and path not in state.get("dirs", [])
    if "dir_exists" in predicate:
        return predicate["dir_exists"] in state.get("dirs", [])
    return False


def validate_plan(
    initial_state: Dict[str, Any],
    plan: List[Dict[str, Any]],
    goal: List[Dict[str, Any]],
    costs: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Mechanical ground truth for one plan. No LLM involved."""
    costs = costs or {}
    world = PWorld(initial_state)
    snapshots = [world.snapshot()]
    first_failure = None
    total_cost = 0.0
    for index, step in enumerate(plan):
        problem = world.check_step(step)
        total_cost += float(costs.get(step.get("action", ""), 1.0))
        if problem is not None and first_failure is None:
            first_failure = {"index": index, "missing": problem, "step": step}
            break  # execution stops at first failure (deterministic semantics)
        world.apply_validated(step)
        snapshots.append(world.snapshot())
    final = world.snapshot()
    missing_goals = [g for g in goal if not predicate_holds(final, g)]
    return {
        "executable": first_failure is None,
        "first_failure": first_failure,
        "goal_reached": not missing_goals,
        "missing_goals": missing_goals,
        "cost": total_cost,
        "snapshots": snapshots,
    }


def _is_path_candidate(value: str) -> bool:
    """True if value looks like a filesystem path (not free-form content)."""
    if not value or " " in value:
        return False
    # contains a separator or a file extension -> path
    if "/" in value:
        return True
    if "." in value and len(value) <= 32:
        base = value.rsplit(".", 1)[-1]
        if base in ("txt", "csv", "json", "md", "log", "tmp"):
            return True
    return False


def _collect_paths(initial_state: Dict[str, Any], goal: List[Dict[str, Any]],
                   plans: List[List[Dict[str, Any]]]) -> List[str]:
    paths = set()
    paths.update(initial_state.get("dirs", []))
    paths.update(initial_state.get("files", {}).keys())
    for pred in goal:
        for key, value in pred.items():
            items = value if isinstance(value, list) else [value]
            for item in items:
                if isinstance(item, str) and _is_path_candidate(item):
                    paths.add(item)
                # 'contains' second element is content — never a path
                if key == "contains" and isinstance(value, list) and len(value) == 2:
                    first = value[0]
                    if isinstance(first, str) and _is_path_candidate(first):
                        paths.add(first)
    for plan in plans:
        for step in plan:
            for arg_key, value in step.get("args", {}).items():
                if arg_key in ("path", "src", "dst") and isinstance(value, str):
                    if _is_path_candidate(value):
                        paths.add(value)
                elif isinstance(value, str) and _is_path_candidate(value):
                    paths.add(value)
    ordered = sorted(paths)
    for path in list(ordered):
        parent = _parent(path)
        while parent and parent not in ordered:
            ordered.append(parent)
            parent = _parent(parent)
    return ordered


def optimal_cost(initial_state: Dict[str, Any], goal: List[Dict[str, Any]],
                 costs: Optional[Dict[str, float]] = None,
                 hint_plans: Optional[List[List[Dict[str, Any]]]] = None) -> float:
    """BFS optimal plan cost over the task's small state space."""
    costs = costs or {}
    paths = _collect_paths(initial_state, goal, hint_plans or [])
    file_paths = [p for p in paths if "." in p.rsplit("/", 1)[-1]]
    dir_paths = [p for p in paths if p not in file_paths]

    def key(state: Dict[str, Any]) -> Tuple:
        return (tuple(sorted(state["dirs"])),
                tuple(sorted(state["files"].items())))

    start = {"dirs": list(initial_state.get("dirs", [])),
             "files": dict(initial_state.get("files", {}))}
    if all(predicate_holds(start, g) for g in goal):
        return 0.0
    # For optimal search, writes to files that have a 'contains' goal must
    # carry satisfying content — empty writes would otherwise never hit the goal.
    required_content: Dict[str, str] = {}
    for pred in goal:
        if "contains" in pred:
            path, text = pred["contains"]
            # keep longest required substring per path
            if len(text) > len(required_content.get(path, "")):
                required_content[path] = text
    queue: deque = deque([(start, 0.0)])
    seen = {key(start)}
    explored = 0
    while queue and explored < BFS_STATE_CAP:
        state, cost = queue.popleft()
        explored += 1
        write_candidates = []
        for p in file_paths:
            content = required_content.get(p, "")
            write_candidates.append({"action": "write_file", "args": {"path": p, "content": content}})
        candidates: List[Dict[str, Any]] = (
            [{"action": "create_dir", "args": {"path": p}} for p in dir_paths]
            + write_candidates
            + [{"action": "move_file", "args": {"src": s, "dst": d}}
               for s in file_paths for d in file_paths if s != d]
            + [{"action": "delete_file", "args": {"path": p}} for p in file_paths]
        )
        for step in candidates:
            probe = PWorld({"dirs": state["dirs"], "files": state["files"]})
            if probe.check_step(step) is not None:
                continue
            probe.apply_validated(step)
            nxt, step_cost = probe.snapshot(), float(costs.get(step["action"], 1.0))
            if all(predicate_holds(nxt, g) for g in goal):
                return cost + step_cost
            k = key(nxt)
            if k not in seen:
                seen.add(k)
                queue.append((nxt, cost + step_cost))
    raise ValueError("BFS exhausted: goal unreachable in capped space")
