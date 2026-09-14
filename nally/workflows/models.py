"""Workflow models — minimal DAG spec for NALLY.

Example workflow.yaml:
  name: support-triage
  nodes:
    - id: classify
      agent: nally
      prompt: "Classify: {{input}}"
      next: [route]
    - id: route
      kind: switch
      cases:
        HIGH_STAKES: human_approval
        COMPLEX: research
      default: answer
    - id: human_approval
      kind: approval
      message: "High-stakes task needs approval"
    - id: research
      tool: web_search
      input: "{{classify.output}}"
    - id: answer
      agent: nally
      prompt: "Answer with context: {{research.output}}"
  edges:
    - from: classify
      to: route

This is intentionally minimal — enough for a2a trigger + human checkpoint + tool call.
Full engine (cron, webhook, durable checkpoint store) is Phase 6; this Phase 5 proves the interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class WorkflowNode:
    id: str
    kind: str = "agent"  # agent | tool | switch | approval
    agent: Optional[str] = None
    tool: Optional[str] = None
    prompt: Optional[str] = None
    input: Optional[str] = None
    cases: Optional[Dict[str, str]] = None
    default: Optional[str] = None
    message: Optional[str] = None
    next: List[str] = field(default_factory=list)


@dataclass
class WorkflowEdge:
    from_id: str
    to_id: str
    condition: Optional[str] = None


@dataclass
class Workflow:
    name: str
    nodes: List[WorkflowNode] = field(default_factory=list)
    edges: List[WorkflowEdge] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "nodes": [n.__dict__ for n in self.nodes],
            "edges": [e.__dict__ for e in self.edges],
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Workflow":
        nodes = [WorkflowNode(**n) for n in data.get("nodes", [])]
        edges = [WorkflowEdge(from_id=e.get("from", e.get("from_id")), to_id=e.get("to", e.get("to_id")), condition=e.get("condition")) for e in data.get("edges", [])]
        return cls(name=data.get("name", "workflow"), nodes=nodes, edges=edges, metadata=data.get("metadata", {}))

    def validate(self) -> List[str]:
        """Return list of errors (empty = valid)."""
        errors = []
        if not self.name:
            errors.append("name required")
        ids = {n.id for n in self.nodes}
        if len(ids) != len(self.nodes):
            errors.append("duplicate node id")
        for e in self.edges:
            if e.from_id not in ids:
                errors.append(f"edge from {e.from_id} not found")
            if e.to_id not in ids:
                errors.append(f"edge to {e.to_id} not found")
        for n in self.nodes:
            if n.kind not in ("agent", "tool", "switch", "approval"):
                errors.append(f"node {n.id} unknown kind {n.kind}")
        return errors
