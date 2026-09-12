"""Capability Router data model — V2 routing types.

CapabilityTag: semantic tags that describe what a tool does.
ToolRoute: maps a tool name to its capabilities, priority, and fallback relationships.
RoutingDecision: the authoritative output of CapabilityRouter.resolve().

This module is pure data — no side effects, no imports from other nally modules.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Dict, List, Optional, Set


class CapabilityTag(StrEnum):
    """Semantic capability tags for tool routing."""

    CODE_EXECUTION = "code_execution"
    FILE_SYSTEM = "file_system"
    WEB = "web"
    EMAIL = "email"
    MEMORY = "memory"
    SUBAGENT = "subagent"
    IMAGE = "image"
    SYSTEM = "system"
    THINKING = "thinking"
    MCP = "mcp"


@dataclass
class ToolRoute:
    """Static routing metadata for a single tool.

    Attributes:
        name: Tool name (matches registry key).
        capabilities: Set of capability tags this tool provides.
        priority: Higher = preferred when multiple tools match the same capability.
        fallback_for: Name of the primary tool this tool can substitute for.
    """

    name: str
    capabilities: Set[CapabilityTag] = field(default_factory=set)
    priority: int = 0
    fallback_for: Optional[str] = None


# ── Static route table for built-in tools ────────────────────
# MCP tools are tagged dynamically at registration time.
BUILTIN_ROUTES: Dict[str, ToolRoute] = {
    # Code execution
    "run_code": ToolRoute(
        name="run_code",
        capabilities={CapabilityTag.CODE_EXECUTION},
        priority=1,
    ),
    "code_analysis": ToolRoute(
        name="code_analysis",
        capabilities={CapabilityTag.CODE_EXECUTION},
        priority=0,
    ),
    # System
    "run_command": ToolRoute(
        name="run_command",
        capabilities={CapabilityTag.CODE_EXECUTION, CapabilityTag.SYSTEM},
        priority=2,
    ),
    "system_health": ToolRoute(
        name="system_health",
        capabilities={CapabilityTag.SYSTEM},
        priority=0,
    ),
    # Files
    "read_file": ToolRoute(
        name="read_file",
        capabilities={CapabilityTag.FILE_SYSTEM},
        priority=1,
    ),
    "file_ops": ToolRoute(
        name="file_ops",
        capabilities={CapabilityTag.FILE_SYSTEM},
        priority=2,
    ),
    # Web
    "web_search": ToolRoute(
        name="web_search",
        capabilities={CapabilityTag.WEB},
        priority=1,
        fallback_for=None,
    ),
    "fetch": ToolRoute(
        name="fetch",
        capabilities={CapabilityTag.WEB},
        priority=0,
        fallback_for="web_search",
    ),
    # Email
    "gmail_read": ToolRoute(
        name="gmail_read",
        capabilities={CapabilityTag.EMAIL},
        priority=1,
    ),
    "gmail_write": ToolRoute(
        name="gmail_write",
        capabilities={CapabilityTag.EMAIL},
        priority=1,
    ),
    # Memory
    "memory": ToolRoute(
        name="memory",
        capabilities={CapabilityTag.MEMORY},
        priority=0,
    ),
    # Subagent
    "agent": ToolRoute(
        name="agent",
        capabilities={CapabilityTag.SUBAGENT},
        priority=0,
    ),
    # Image
    "generate_image": ToolRoute(
        name="generate_image",
        capabilities={CapabilityTag.IMAGE},
        priority=0,
    ),
    "analyze_image": ToolRoute(
        name="analyze_image",
        capabilities={CapabilityTag.IMAGE},
        priority=0,
    ),
    "edit_image": ToolRoute(
        name="edit_image",
        capabilities={CapabilityTag.IMAGE},
        priority=0,
    ),
    # Thinking
    "think": ToolRoute(
        name="think",
        capabilities={CapabilityTag.THINKING},
        priority=0,
    ),
    # Web design
    "web_design": ToolRoute(
        name="web_design",
        capabilities={CapabilityTag.WEB, CapabilityTag.IMAGE},
        priority=0,
    ),
    # Task state
    "task_state": ToolRoute(
        name="task_state",
        capabilities={CapabilityTag.SYSTEM},
        priority=0,
    ),
}


@dataclass
class RoutingDecision:
    """Authoritative output of CapabilityRouter.resolve().

    This is the single object every tool-selection caller receives.
    Callers that only need schemas should use ``decision.schemas``.
    Callers that need routing metadata can inspect ``available`` and ``denied``.
    """

    schemas: List[Dict[str, Any]]
    available: Set[str]
    denied: Set[str]
    task_class: str = ""
    enforcement: str = "permissive"  # "permissive" | "strict"

    def __iter__(self):
        """Backward-compat: allow ``for schema in decision:`` iteration."""
        return iter(self.schemas)

    def __len__(self):
        return len(self.schemas)

    def __bool__(self):
        return bool(self.schemas)
