"""Tool Filter — keyword-based tool selection for LLM requests.

Selects a relevant subset of tools per-request to reduce prompt size.
Keyword-only (no embeddings) for determinism and prompt-cache stability.
"""

import re
from typing import Dict, List, Set

from .registry import Tool


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

    def build_index(self, tools: Dict[str, Tool]):
        """Index tool names and descriptions for keyword matching."""
        self._tool_names = dict(tools)
        self._tool_keywords = {}
        self._all_schemas = []

        for name, tool in tools.items():
            tokens = _tokenize(name) | _tokenize(tool.description)
            self._tool_keywords[name] = tokens
            self._all_schemas.append(tool.to_openai_schema())

        self._ready = True

    def select(self, query: str) -> List[dict]:
        """Return OpenAI tool schemas relevant to the query.

        Strategy: keyword overlap between query and tool index.
        If no strong match (overlap < 2 tokens), return all tools
        to preserve prompt-cache prefix stability.
        """
        if not self._ready or not self._tool_keywords:
            return self._all_schemas

        query_tokens = _tokenize(query)
        if not query_tokens:
            return self._all_schemas

        scored: List[tuple] = []
        for name, tool_tokens in self._tool_keywords.items():
            overlap = query_tokens & tool_tokens
            if overlap:
                scored.append((name, len(overlap)))

        # No matches → return all (cache-safe fallback)
        if not scored:
            return self._all_schemas

        # Sort by overlap count, take top matches
        scored.sort(key=lambda x: x[1], reverse=True)

        # If best match is weak (1 token), still return all — not worth
        # breaking cache prefix for a single-word hit
        if scored[0][1] < 2:
            return self._all_schemas

        # Build result: matched tools + always-on tools (system_health is
        # always useful for diagnostics)
        always_on = {"system_health", "web_search"}
        selected_names = always_on | {name for name, _ in scored}

        return [self._tool_names[name].to_openai_schema() for name in selected_names if name in self._tool_names]


# Module-level singleton — matches existing call pattern in core.py and agent.py
tool_filter = ToolFilter()
