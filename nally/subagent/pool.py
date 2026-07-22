"""SubAgentPool - Manages creation, execution, and result collection of sub-agents"""
import threading
import time
from typing import Dict, List, Optional, Callable, Any
from .agent import SubAgent
from ..utils.logger import logger


class SubAgentPool:
    """Thread-safe pool for spawning and managing sub-agents"""

    def __init__(self):
        self._agents: Dict[str, SubAgent] = {}
        self._lock = threading.Lock()
        self._total_spawned = 0

    def spawn(self, goal: str, context: str = "", emit: Optional[Callable] = None) -> str:
        """Spawn a single sub-agent"""
        agent = SubAgent(goal=goal, context=context)
        agent.set_callback(emit)
        agent.start(emit)

        with self._lock:
            self._agents[agent.id] = agent
            self._total_spawned += 1

        return agent.id

    def spawn_many(self, tasks: List[Dict], emit: Optional[Callable] = None) -> List[str]:
        """Spawn multiple sub-agents in parallel. Each task: {goal, context}"""
        ids = []
        for task in tasks:
            agent_id = self.spawn(task.get("goal", ""), task.get("context", ""), emit)
            ids.append(agent_id)

        return ids

    def get_status(self, agent_id: str) -> Optional[dict]:
        """Get status of a single sub-agent"""
        with self._lock:
            agent = self._agents.get(agent_id)
        if agent:
            return agent.get_status()
        return None

    def get_results(self, agent_ids: List[str]) -> List[dict]:
        """Get results for multiple sub-agents"""
        results = []
        for aid in agent_ids:
            status = self.get_status(aid)
            if status:
                results.append(status)
        return results

    def get_completed(self, agent_ids: List[str]) -> List[dict]:
        """Get only completed sub-agent results"""
        results = self.get_results(agent_ids)
        return [r for r in results if r.get("status") == "completed"]

    def get_all_status(self) -> List[dict]:
        """Get status of all sub-agents"""
        with self._lock:
            return [a.get_status() for a in self._agents.values()]

    def get_running(self) -> List[dict]:
        """Get status of all running sub-agents"""
        all_status = self.get_all_status()
        return [s for s in all_status if s.get("status") == "running"]

    def cancel(self, agent_id: str) -> bool:
        """Cancel a sub-agent (mark as cancelled)"""
        with self._lock:
            agent = self._agents.get(agent_id)
        if agent and agent.status in ("pending", "running"):
            agent.status = "cancelled"
            agent.completed_at = __import__('datetime').datetime.now().isoformat()
            return True
        return False

    def cancel_all(self):
        """Cancel all running sub-agents"""
        with self._lock:
            for agent in self._agents.values():
                if agent.status in ("pending", "running"):
                    agent.status = "cancelled"

    def wait_for_all(self, timeout: float = 300.0):
        """Wait for all sub-agents to complete"""
        with self._lock:
            agents = list(self._agents.values())

        for agent in agents:
            if agent.status in ("pending", "running"):
                agent.wait(timeout)

    def collect_finished(self) -> List[dict]:
        """Collect results from finished agents and remove them from the pool"""
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
        """Get pool statistics"""
        with self._lock:
            total = len(self._agents)
            running = sum(1 for a in self._agents.values() if a.status == "running")
            completed = sum(1 for a in self._agents.values() if a.status == "completed")
            pending = sum(1 for a in self._agents.values() if a.status == "pending")
            failed = sum(1 for a in self._agents.values() if a.status == "failed")

        return {
            "total": total,
            "running": running,
            "completed": completed,
            "pending": pending,
            "failed": failed,
            "total_spawned_all_time": self._total_spawned,
        }

    def clear(self):
        """Clear all completed agents from the pool"""
        with self._lock:
            to_remove = []
            for aid, agent in self._agents.items():
                if agent.status in ("completed", "failed", "cancelled"):
                    to_remove.append(aid)
            for aid in to_remove:
                del self._agents[aid]


pool = SubAgentPool()
