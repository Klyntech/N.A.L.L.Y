"""Tool Filter — keyword-based tool selection for LLM requests.

Selects a relevant subset of tools per-request to reduce prompt size.
Keyword-only (no embeddings) for determinism and prompt-cache stability.
"""

import re
from typing import Dict, List, Set

from .registry import Tool

# Core built-in tools — always included (small schema footprint)
CORE_TOOLS = {
    "run_command",
    "system_health",
    "mcp_status",
    "read_file",
    "file_ops",
    "run_code",
    "code_analysis",
    "web_search",
    "generate_image",
    "memory_stats",
    "think",
    # Gmail direct tools
    "gmail_search",
    "gmail_read_thread",
    "gmail_labels",
    "gmail_profile",
    # Subagent
    "agent",
    # NallyBridge
    "bridge_execute",
    # Phone calls
    "make_call",
    "get_call_status",
    "hangup_call",
    "list_calls",
}

# Tools always included in filtered results regardless of query
ALWAYS_ON = {"system_health", "web_search", "mcp_status", "run_command", "read_file", "file_ops"}


def _tokenize(text: str) -> Set[str]:
    """Lowercase, split on non-alphanumeric, drop short tokens."""
    return {t for t in re.split(r"[^a-z0-9]+", text.lower()) if len(t) > 2}


class ToolFilter:
    """Build a keyword index over tools, select relevant subset per query."""

    def __init__(self):
        self._ready = False
        self._tool_names: Dict[str, Tool] = {}
        self._tool_keywords: Dict[str, Set[str]] = {}
        self._all_schemas: List[dict] = []
        self._core_schemas: List[dict] = []

    def build_index(self, tools: Dict[str, Tool]):
        """Index tool names and descriptions for keyword matching."""
        self._tool_names = dict(tools)
        self._tool_keywords = {}
        self._all_schemas = []
        self._core_schemas = []

        for name, tool in tools.items():
            tokens = _tokenize(name) | _tokenize(tool.description)
            self._tool_keywords[name] = tokens
            schema = tool.to_openai_schema()
            self._all_schemas.append(schema)
            if name in CORE_TOOLS:
                self._core_schemas.append(schema)

        self._ready = True

    def select(self, query: str, task_class: str = "") -> List[dict]:
        """Return OpenAI tool schemas relevant to the query.

        Strategy: keyword overlap between query and tool index.
        - Strong match (>=2 tokens): return matched tools + core
        - Weak/no match: return core tools only (avoids bloating context
          with 200+ MCP tool schemas when they're not relevant)
        - Complex/High-Stakes tasks: return core + all matched (broader set)
        """
        if not self._ready or not self._tool_keywords:
            return self._all_schemas

        query_tokens = _tokenize(query)
        if not query_tokens:
            return self._core_schemas

        scored: List[tuple] = []
        for name, tool_tokens in self._tool_keywords.items():
            overlap = query_tokens & tool_tokens
            if overlap:
                scored.append((name, len(overlap)))

        # No matches → return core only (not all 300+ tools)
        if not scored:
            return self._core_schemas

        # Sort by overlap count, take top matches
        scored.sort(key=lambda x: x[1], reverse=True)

        # Complex/High-Stakes tasks get broader tool set (all matched + core)
        if task_class in ("COMPLEX", "HIGH_STAKES"):
            always_on = ALWAYS_ON
            selected_names = always_on | {name for name, _ in scored}
            return [self._tool_names[name].to_openai_schema() for name in selected_names if name in self._tool_names]

        # Weak match (1 token) → return core + top 10 matched (not all)
        if scored[0][1] < 2:
            always_on = ALWAYS_ON
            selected_names = always_on | {name for name, _ in scored[:10]}
            return [self._tool_names[name].to_openai_schema() for name in selected_names if name in self._tool_names]

        # Strong match → return matched tools + core
        always_on = ALWAYS_ON
        selected_names = always_on | {name for name, _ in scored}

        return [self._tool_names[name].to_openai_schema() for name in selected_names if name in self._tool_names]


# Module-level singleton — matches existing call pattern in core.py and agent.py
tool_filter = ToolFilter()
