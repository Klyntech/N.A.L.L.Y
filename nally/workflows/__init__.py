"""Workflows — declarative DAG for NALLY (lesson 16).

Three planes: Hosted (Render) | Client (CLI) | Workflows (DAG).
Workflows are YAML/JSON DAGs of agents/tools with durable checkpoints, human-in-the-loop, and cron/webhook triggers.
Kept separate from nally/agent/planner.py (LLM-generated plan steps) — workflows are user-defined, not LLM-generated.
"""

from .models import Workflow, WorkflowEdge, WorkflowNode
from .runner import run_workflow

__all__ = ["Workflow", "WorkflowNode", "WorkflowEdge", "run_workflow"]
