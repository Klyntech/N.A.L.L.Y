"""Capability Router — authoritative entry point for tool selection.

V2 architecture: every tool-selection caller goes through this module.
ToolFilter and PermissionGate are mechanisms; this module is the control surface.

Resolution flow:
    CapabilityRouter.resolve(query, task_class)
        → ToolFilter.select(query, task_class)       # keyword narrowing
        → PermissionGate.check(name, args)            # allow/ask/deny
        → RoutingDecision(schemas, available, denied)

Backward compat: RoutingDecision is iterable and len()-able, so callers
that previously used ``tools = router.resolve(query)`` still work.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from .router_types import BUILTIN_ROUTES, CapabilityTag, RoutingDecision, ToolRoute

logger = logging.getLogger("nally.capability_router")


class CapabilityRouter:
    """Resolve capabilities by intent; return a RoutingDecision."""

    def __init__(self):
        self._routes: Dict[str, ToolRoute] = dict(BUILTIN_ROUTES)

    def register_route(self, route: ToolRoute):
        """Register a tool route (called for MCP tools at connect time)."""
        self._routes[route.name] = route

    def get_route(self, tool_name: str) -> Optional[ToolRoute]:
        """Return the static route for a tool, or None."""
        return self._routes.get(tool_name)

    def resolve(
        self,
        query: str,
        task_class: str = "",
        *,
        enforce_permissions: bool = True,
    ) -> RoutingDecision:
        """Return permission-aware tool schemas for this turn.

        1. filter.select(query, task_class) narrows the set.
        2. permissions gate drops DENY tools (ASK tools stay; the graph
           owns the approval UX at execution time).
        """
        # ── Step 1: keyword filtering ──
        schemas: List[Dict[str, Any]] = []
        try:
            from .filter import tool_filter
            from .registry import registry

            if not tool_filter._ready:
                try:
                    tool_filter.build_index(registry.tools)
                except Exception:
                    pass
            schemas = tool_filter.select(query or "", task_class=task_class or "")
        except Exception as e:
            logger.debug(f"CapabilityRouter filter fallback: {e}")
            try:
                from .registry import registry

                schemas = [t.to_openai_schema() for t in registry.tools.values()]
            except Exception:
                return RoutingDecision(
                    schemas=[], available=set(), denied=set(), task_class=task_class
                )

        # ── Step 2: permission filtering ──
        available: Set[str] = set()
        denied: Set[str] = set()

        if not enforce_permissions:
            available = self._extract_names(schemas)
            return RoutingDecision(
                schemas=schemas,
                available=available,
                denied=denied,
                task_class=task_class,
                enforcement="permissive",
            )

        try:
            from .permissions import gate

            kept: List[Dict[str, Any]] = []
            for s in schemas:
                name = self._extract_name(s)
                if not name:
                    kept.append(s)
                    continue
                try:
                    verdict = gate.check(name, {})
                    if str(verdict).lower() == "deny":
                        denied.add(name)
                        continue
                except Exception:
                    pass
                kept.append(s)
                available.add(name)
            schemas = kept
        except Exception as e:
            logger.debug(f"CapabilityRouter permission pass skipped: {e}")
            available = self._extract_names(schemas)

        return RoutingDecision(
            schemas=schemas,
            available=available,
            denied=denied,
            task_class=task_class,
            enforcement="strict",
        )

    def suggest_fallback(
        self, failed_tool: str, query: str = ""
    ) -> Optional[ToolRoute]:
        """Suggest the highest-priority alternative for a failed tool.

        Returns a ToolRoute with ``fallback_for == failed_tool``, or the
        best alternative with overlapping capabilities if no explicit
        fallback is declared. Returns None if no alternative exists.

        This method is pure — it does not execute anything or change state.
        Phase 5 proves the interface; Phase 6 activates it in the graph.
        """
        failed_route = self._routes.get(failed_tool)
        if not failed_route:
            return None

        # 1. Explicit fallback_for declarations
        candidates: List[ToolRoute] = []
        for route in self._routes.values():
            if route.fallback_for == failed_tool:
                candidates.append(route)

        if candidates:
            candidates.sort(key=lambda r: r.priority, reverse=True)
            return candidates[0]

        # 2. Capability overlap (same tags, different tool)
        if failed_route.capabilities:
            for route in self._routes.values():
                if route.name == failed_tool:
                    continue
                if route.capabilities & failed_route.capabilities:
                    candidates.append(route)

        if candidates:
            candidates.sort(key=lambda r: r.priority, reverse=True)
            return candidates[0]

        return None

    def check_execution(self, tool_name: str, args: Optional[Dict[str, Any]] = None):
        """Delegate to permissions gate for execution-time enforcement."""
        from .permissions import gate

        return gate.check(tool_name, args or {})

    @staticmethod
    def _extract_name(schema: Dict[str, Any]) -> str:
        """Extract tool name from an OpenAI schema dict."""
        try:
            fn = schema.get("function", schema)
            return str(fn.get("name", ""))
        except Exception:
            return ""

    @staticmethod
    def _extract_names(schemas: List[Dict[str, Any]]) -> Set[str]:
        """Extract all tool names from a list of schemas."""
        names: Set[str] = set()
        for s in schemas:
            name = CapabilityRouter._extract_name(s)
            if name:
                names.add(name)
        return names


capability_router = CapabilityRouter()
