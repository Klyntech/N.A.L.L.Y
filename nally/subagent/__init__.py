"""SubAgent System - Autonomous parallel sub-agents with full LLM reasoning"""
from .agent import SubAgent
from .pool import pool as subagent_pool, SubAgentPool
from .decomposer import decomposer, TaskDecomposer

__all__ = ["SubAgent", "subagent_pool", "SubAgentPool", "decomposer", "TaskDecomposer"]
