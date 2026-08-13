"""SubAgentPool - Manages creation, execution, and result collection of sub-agents"""

import contextvars
import logging
import threading
from datetime import datetime
from typing import Callable, Dict, List, Optional

from .agent import SubAgent
from ..config import MAX_SUBAGENT_DEPTH
from ..core.tracing import tracer

logger = logging.getLogger("nally.subagent.pool")

# Tracks the current sub-agent nesting depth. Propagated into tool-executor
# worker threads via contextvars so a sub-agent that spawns further sub-agents
# is correctly bounded by MAX_SUBAGENT_DEPTH (prevents agent→agent→agent… → ∞).
SUBAGENT_DEPTH = contextvars.ContextVar("nally_subagent_depth", default=0)


class SubAgentPool:
    """Thread-safe pool for spawning and managing sub-agents"""

    def __init__(self):
        self._agents: Dict[str, SubAgent] = {}
        self._lock = threading.Lock()
        self._total_spawned = 0

    def spawn(
        self,
        goal: str,
        context: str = "",
        emit: Optional[Callable] = None,
        model: Optional[str] = None,
        depth: Optional[int] = None,
    ) -> Optional[str]:
        """Spawn a single sub-agent.

        Args:
            depth: Nesting depth of this spawn. If None, read from the
                SUBAGENT_DEPTH contextvar (set by the parent sub-agent).

        Returns:
            The new sub-agent id, or None if the depth limit was reached.
        """
        if depth is None:
            depth = SUBAGENT_DEPTH.get()

        # Hard circuit breaker: refuse to spawn beyond MAX_SUBAGENT_DEPTH.
        if depth >= MAX_SUBAGENT_DEPTH:
            logger.warning(
                f"SubAgent depth limit ({MAX_SUBAGENT_DEPTH}) reached at depth {depth} — refusing to spawn deeper"
            )
            return None

        # Capture the parent span context now (this thread's span stack does not
        # propagate into the sub-agent's own thread).
        cur_span = tracer.get_current_span()
        parent_id = cur_span.span_id if cur_span else None
        run_id = cur_span.run_id if cur_span else None

        agent = SubAgent(goal=goal, context=context, model=model, depth=depth + 1)
        agent.set_trace_context(parent_id, run_id)
        agent.set_callback(emit)
        agent.start(emit)

        with self._lock:
            self._agents[agent.id] = agent
            self._total_spawned += 1

        return agent.id

    def spawn_many(self, tasks: List[Dict], emit: Optional[Callable] = None, model: Optional[str] = None, depth: Optional[int] = None) -> List[Optional[str]]:
        """Spawn multiple sub-agents in parallel. Each task: {goal, context}"""
        return [
            self.spawn(
                t.get("goal", "") if isinstance(t, dict) else str(t),
                t.get("context", "") if isinstance(t, dict) else "",
                emit,
                model=model,
                depth=depth,
            )
            for t in tasks
        ]

    def get_status(self, agent_id: str) -> Optional[dict]:
        """Get status of a single sub-agent."""
        with self._lock:
            agent = self._agents.get(agent_id)
        return agent.get_status() if agent else None

    def get_results(self, agent_ids: List[str]) -> List[dict]:
        """Get results for multiple sub-agents."""
        return [s for aid in agent_ids if (s := self.get_status(aid))]

    def get_completed(self, agent_ids: List[str]) -> List[dict]:
        """Get only completed sub-agent results."""
        return [r for r in self.get_results(agent_ids) if r.get("status") == "completed"]

    def get_all_status(self) -> List[dict]:
        """Get status of all sub-agents."""
        with self._lock:
            return [a.get_status() for a in self._agents.values()]

    def get_running(self) -> List[dict]:
        """Get status of all running sub-agents."""
        return [s for s in self.get_all_status() if s.get("status") == "running"]

    def cancel(self, agent_id: str) -> bool:
        """Cancel a sub-agent (mark as cancelled)."""
        with self._lock:
            agent = self._agents.get(agent_id)
        if agent and agent.status in ("pending", "running"):
            agent.status = "cancelled"
            agent.completed_at = datetime.now().isoformat()
            return True
        return False

    def cancel_all(self):
        """Cancel all running sub-agents."""
        with self._lock:
            for agent in self._agents.values():
                if agent.status in ("pending", "running"):
                    agent.status = "cancelled"

    def wait_for_all(self, timeout: float = 300.0):
        """Wait for all sub-agents to complete."""
        with self._lock:
            agents = list(self._agents.values())
        for agent in agents:
            if agent.status in ("pending", "running"):
                agent.wait(timeout)

    def collect_finished(self) -> List[dict]:
        """Collect results from finished agents and remove them from the pool."""
        with self._lock:
            finished = []
            to_remove = []
            for aid, agent in self._agents.items():
                if agent.status in ("completed", "failed", "cancelled"):
                    finished.append(agent.get_status())
                    to_remove.append(aid)
            for aid in to_remove:
                del self._agents[aid]
            return finished

    def get_stats(self) -> dict:
        """Get pool statistics."""
        with self._lock:
            statuses = [a.status for a in self._agents.values()]
        return {
            "total": len(statuses),
            "running": statuses.count("running"),
            "completed": statuses.count("completed"),
            "pending": statuses.count("pending"),
            "failed": statuses.count("failed"),
            "total_spawned_all_time": self._total_spawned,
        }

    def clear(self):
        """Clear all completed agents from the pool."""
        with self._lock:
            to_remove = [
                aid for aid, agent in self._agents.items() if agent.status in ("completed", "failed", "cancelled")
            ]
            for aid in to_remove:
                del self._agents[aid]


pool = SubAgentPool()
