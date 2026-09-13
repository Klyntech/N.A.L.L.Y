"""Suite A task schema — reuses Suite T's state DAG model.

Suite A evaluates BEHAVIORAL TRAJECTORIES (tool choice, state tracking,
recovery, multi-step, uncertainty) across 6 envs, not just final answers.
Each task still defines initial_state -> dependency_graph -> milestones
-> terminal_state -> minefields, scored on state transitions.
"""
from pathlib import Path
from typing import List, Optional

from tests.eval.suite_t.schema import Milestone, TaskSpec, load_task, task_from_dict


def load_all_tasks(tasks_dir: Optional[Path] = None) -> List[TaskSpec]:
    if tasks_dir is None:
        tasks_dir = Path(__file__).parent / "tasks"
    tasks = []
    for jf in sorted(Path(tasks_dir).glob("*.json")):
        tasks.append(load_task(jf))
    return tasks

__all__ = ["Milestone", "TaskSpec", "load_all_tasks", "load_task", "task_from_dict"]
