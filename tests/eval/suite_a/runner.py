"""Suite A runner/scorer — thin aliases to Suite T (same world, DAG scoring).

Trajectory = state transitions; metrics identical so Phase 4 comparisons
across T/P/A/C share the same score contract (milestones x minefields).
"""

from tests.eval.suite_a.schema import load_all_tasks
from tests.eval.suite_t.runner import gold_trajectory, noop_trajectory, replay, run_suite
from tests.eval.suite_t.scorer import score_trajectory
from tests.eval.suite_t.world import SimWorld

__all__ = ["SimWorld", "gold_trajectory", "load_all_tasks", "noop_trajectory", "replay", "run_suite", "score_trajectory"]
