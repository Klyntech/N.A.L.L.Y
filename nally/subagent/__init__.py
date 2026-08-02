"""SubAgent System - Autonomous parallel sub-agents with full LLM reasoning"""

from .agent import SubAgent
from .decomposer import TaskDecomposer, decomposer
from .pool import SubAgentPool
from .pool import pool as subagent_pool

__all__ = ["SubAgent", "SubAgentPool", "TaskDecomposer", "decomposer", "subagent_pool"]
