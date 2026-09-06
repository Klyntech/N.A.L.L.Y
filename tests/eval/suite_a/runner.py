"""Suite A runner/scorer — thin aliases to Suite T (same world, DAG scoring).

Trajectory = state transitions; metrics identical so Phase 4 comparisons
across T/P/A/C share the same score contract (milestones x minefields).
"""

from tests.eval.suite_t.scorer import score_trajectory  # noqa: F401
from tests.eval.suite_t.world import SimWorld  # noqa: F401
from tests.eval.suite_t.runner import gold_trajectory, noop_trajectory, replay, run_suite  # noqa: F401
from tests.eval.suite_a.schema import load_all_tasks  # noqa: F401

__all__ = ["score_trajectory", "SimWorld", "gold_trajectory", "noop_trajectory", "replay", "run_suite", "load_all_tasks"]
