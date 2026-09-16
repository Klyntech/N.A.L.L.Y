"""Tool Filter — keyword-based tool selection for LLM requests.

Selects a relevant subset of tools per-request to reduce prompt size.
Keyword-only (no embeddings) for determinism and prompt-cache stability.
"""

import hashlib
import re
import time
from typing import Dict, List, Set, Tuple

from .registry import Tool

_filter_cache: Dict[str, Tuple[float, List[dict]]] = {}
_FILTER_TTL = 300

# Core built-in tools — always included (small schema footprint)
# run_command removed — shell OOM hardening
CORE_TOOLS = {
    "system_health",
    "read_file",
    "file_ops",
    "run_code",
    "code_analysis",
    "web_search",
    "generate_image",
    "memory",
    "think",
    # Gmail capability (read side always visible; write stays keyword-gated)
    "gmail_read",
    # Subagent
    "agent",
}

# Tools always included in filtered results regardless of query
ALWAYS_ON = {"system_health", "web_search", "read_file", "file_ops"}


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
        - Empty/no-match: return core tools (small, always-safe fallback).
        - Strong match (>=2 tokens): ALWAYS_ON(5) + all matched.
        - Weak match (1 token): ALWAYS_ON + top 10 matched.
        - Complex/High-Stakes: ALWAYS_ON + all matched (uncapped; strong
          and weak share this path, unlike SIMPLE which caps weak at 10).

        Cached per (query, task_class) for 5m to avoid recomputing select()
        on repeated identical turns (lesson 16 caching).
        """
        cache_key = hashlib.sha256(f"{query}::{task_class}".encode()).hexdigest()
        now = time.time()
        cached = _filter_cache.get(cache_key)
        if cached and now - cached[0] < _FILTER_TTL:
            return cached[1]

        if not self._ready or not self._tool_keywords:
            result = self._all_schemas
            _filter_cache[cache_key] = (now, result)
            return result

        query_tokens = _tokenize(query)
        if not query_tokens:
            result = self._core_schemas
            _filter_cache[cache_key] = (now, result)
            return result

        scored: List[tuple] = []
        for name, tool_tokens in self._tool_keywords.items():
            overlap = query_tokens & tool_tokens
            if overlap:
                scored.append((name, len(overlap)))

        # No matches → return core only (not all 300+ tools)
        if not scored:
            result = self._core_schemas
            _filter_cache[cache_key] = (now, result)
            if len(_filter_cache) > 500:
                oldest = sorted(_filter_cache.items(), key=lambda kv: kv[1][0])[:100]
                for k, _ in oldest:
                    _filter_cache.pop(k, None)
            return result

        # Sort by overlap count, take top matches
        scored.sort(key=lambda x: x[1], reverse=True)

        # Complex/High-Stakes tasks get broader tool set (all matched + ALWAYS_ON, uncapped)
        if task_class in ("COMPLEX", "HIGH_STAKES"):
            always_on = ALWAYS_ON
            selected_names = always_on | {name for name, _ in scored}
            result = [self._tool_names[name].to_openai_schema() for name in selected_names if name in self._tool_names]
            _filter_cache[cache_key] = (now, result)
            if len(_filter_cache) > 500:
                oldest = sorted(_filter_cache.items(), key=lambda kv: kv[1][0])[:100]
                for k, _ in oldest:
                    _filter_cache.pop(k, None)
            return result

        # Weak match (1 token) → ALWAYS_ON + top 10 matched
        if scored[0][1] < 2:
            always_on = ALWAYS_ON
            selected_names = always_on | {name for name, _ in scored[:10]}
            result = [self._tool_names[name].to_openai_schema() for name in selected_names if name in self._tool_names]
            _filter_cache[cache_key] = (now, result)
            if len(_filter_cache) > 500:
                oldest = sorted(_filter_cache.items(), key=lambda kv: kv[1][0])[:100]
                for k, _ in oldest:
                    _filter_cache.pop(k, None)
            return result

        # Strong match → ALWAYS_ON + all matched
        always_on = ALWAYS_ON
        selected_names = always_on | {name for name, _ in scored}
        result = [self._tool_names[name].to_openai_schema() for name in selected_names if name in self._tool_names]
        _filter_cache[cache_key] = (now, result)
        if len(_filter_cache) > 500:
            oldest = sorted(_filter_cache.items(), key=lambda kv: kv[1][0])[:100]
            for k, _ in oldest:
                _filter_cache.pop(k, None)
        return result


# Module-level singleton — matches existing call pattern in core.py and agent.py
tool_filter = ToolFilter()
