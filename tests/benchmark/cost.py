"""Cost tracking — token aggregation per task and per model.

Reads from context_manager.get_stats() and receipt store.
No dollar conversion — just token counts and latencies.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class TaskCost:
    task_id: str
    tokens_in: int = 0
    tokens_out: int = 0
    total_tokens: int = 0
    latency_ms: float = 0.0
    tool_latencies_ms: List[float] = field(default_factory=list)
    num_llm_calls: int = 0
    num_tool_calls: int = 0

    @property
    def avg_tool_latency_ms(self) -> float:
        if not self.tool_latencies_ms:
            return 0.0
        return sum(self.tool_latencies_ms) / len(self.tool_latencies_ms)


@dataclass
class ModelCostSummary:
    model: str
    tasks_run: int = 0
    total_tokens_in: int = 0
    total_tokens_out: int = 0
    total_tokens: int = 0
    total_latency_ms: float = 0.0
    task_costs: List[TaskCost] = field(default_factory=list)

    @property
    def avg_tokens_per_task(self) -> float:
        return self.total_tokens / max(1, self.tasks_run)

    @property
    def avg_latency_ms(self) -> float:
        return self.total_latency_ms / max(1, self.tasks_run)

    @property
    def avg_tokens_in(self) -> float:
        return self.total_tokens_in / max(1, self.tasks_run)

    @property
    def avg_tokens_out(self) -> float:
        return self.total_tokens_out / max(1, self.tasks_run)


class CostTracker:
    """Tracks token usage and latency across benchmark tasks."""

    def __init__(self):
        self._summaries: Dict[str, ModelCostSummary] = {}
        self._task_costs: List[TaskCost] = []
        self._snapshots: Dict[str, Dict] = {}  # task_id -> stats snapshot

    def snapshot(self, task_id: str, stats: Dict):
        """Take a snapshot of context_manager.get_stats() before a task runs."""
        self._snapshots[task_id] = {
            "total_tokens_in": stats.get("total_tokens_in", 0),
            "total_tokens_out": stats.get("total_tokens_out", 0),
            "total_requests": stats.get("total_requests", 0),
            "timestamp": time.time(),
        }

    def record_task(
        self,
        task_id: str,
        model: str,
        stats_after: Dict,
        latency_ms: float,
        tool_latencies_ms: Optional[List[float]] = None,
        num_tool_calls: int = 0,
    ):
        """Record cost for a completed task by diffing before/after snapshots."""
        before = self._snapshots.get(task_id, {})

        tokens_in = stats_after.get("total_tokens_in", 0) - before.get("total_tokens_in", 0)
        tokens_out = stats_after.get("total_tokens_out", 0) - before.get("total_tokens_out", 0)
        llm_calls = stats_after.get("total_requests", 0) - before.get("total_requests", 0)

        tc = TaskCost(
            task_id=task_id,
            tokens_in=max(0, tokens_in),
            tokens_out=max(0, tokens_out),
            total_tokens=max(0, tokens_in + tokens_out),
            latency_ms=latency_ms,
            tool_latencies_ms=tool_latencies_ms or [],
            num_llm_calls=max(0, llm_calls),
            num_tool_calls=num_tool_calls,
        )
        self._task_costs.append(tc)

        # Update model summary
        if model not in self._summaries:
            self._summaries[model] = ModelCostSummary(model=model)
        s = self._summaries[model]
        s.tasks_run += 1
        s.total_tokens_in += tc.tokens_in
        s.total_tokens_out += tc.tokens_out
        s.total_tokens += tc.total_tokens
        s.total_latency_ms += tc.latency_ms
        s.task_costs.append(tc)

    def get_summary(self, model: str) -> Optional[ModelCostSummary]:
        return self._summaries.get(model)

    def get_all_summaries(self) -> Dict[str, ModelCostSummary]:
        return dict(self._summaries)

    def get_task_costs(self) -> List[TaskCost]:
        return list(self._task_costs)

    def to_dict(self) -> Dict:
        return {
            "models": {
                m: {
                    "tasks_run": s.tasks_run,
                    "total_tokens_in": s.total_tokens_in,
                    "total_tokens_out": s.total_tokens_out,
                    "total_tokens": s.total_tokens,
                    "avg_tokens_per_task": s.avg_tokens_per_task,
                    "avg_latency_ms": s.avg_latency_ms,
                }
                for m, s in self._summaries.items()
            },
            "task_costs": [
                {
                    "task_id": tc.task_id,
                    "tokens_in": tc.tokens_in,
                    "tokens_out": tc.tokens_out,
                    "total_tokens": tc.total_tokens,
                    "latency_ms": tc.latency_ms,
                    "num_tool_calls": tc.num_tool_calls,
                }
                for tc in self._task_costs
            ],
        }
