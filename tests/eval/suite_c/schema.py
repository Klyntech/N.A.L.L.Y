"""Suite C — controlled-context suite (per Phase 2 matrix).

Tests hypotheses around: context placement, memory limits, document budgets,
retrieval/reranking, tool availability. Each task is state-based and
deterministic; the experimental CONDITIONS (placement, budget, rerank) are
applied test-side by the harness running the SAME tasks with different assembly.
Suite C tasks themselves just provide the substrate (docs, budgets, gold).
"""
from pathlib import Path
from typing import List, Optional
from tests.eval.suite_t.schema import Milestone, TaskSpec, task_from_dict, load_task

def load_all_tasks(tasks_dir: Optional[Path] = None) -> List[TaskSpec]:
    if tasks_dir is None: tasks_dir = Path(__file__).parent / "tasks"
    tasks=[]
    for jf in sorted(Path(tasks_dir).glob("*.json")): tasks.append(load_task(jf))
    return tasks

__all__=["Milestone","TaskSpec","task_from_dict","load_task","load_all_tasks"]
