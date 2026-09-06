"""
Wave 1 — Result schema (immutable benchmark consumer).

Every result file is validated against this schema before being considered
a Wave 1 data point. Substrate files (80 tasks + scorers) are never written.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional
import json
import time

from .config import FROZEN

@dataclass
class TaskResult:
    provider: str
    experiment_id: str  # E-H1, E-H2, ...
    arm: str
    task_id: str
    suite: str  # suite_t, suite_p, suite_a, suite_c
    score: float  # primary: milestone similarity x minefield (T/A/C) or task-type scorer (P)
    milestone_similarity: float
    minefield_hits: List[str]
    diagnostics: Dict[str, Any]
    # audit trail
    tool_calls: List[Dict[str, Any]]  # truncated results, full args
    budget_used: Dict[str, Any]  # {tool_calls, wall_ms, retries}
    temperature: float
    tool_set_mode: str
    context_placement: str
    seed: int
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    config_fingerprint: str = field(default_factory=lambda: FROZEN.fingerprint())
    config_version: str = field(default_factory=lambda: FROZEN.version)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str)

@dataclass
class ExperimentSummary:
    experiment_id: str
    arm: str
    provider: str
    total: int
    mean_score: float
    by_suite: Dict[str, float]
    by_category: Dict[str, float]
    config_fingerprint: str = field(default_factory=lambda: FROZEN.fingerprint())
    config_version: str = field(default_factory=lambda: FROZEN.version)
    timestamp: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    results: List[TaskResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        # keep per-task results serializable
        d["results"] = [r.to_dict() if isinstance(r, TaskResult) else r for r in self.results]
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, default=str)
