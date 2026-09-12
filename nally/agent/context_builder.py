"""Nally Context Builder — typed construction of the exact context given to the model.

Replaces the imperative prune→compact→inject sequence in core._llm_process
with a pure, testable builder returning a typed BuiltContext.

V2 diagram:
  INPUT (typed Input) + SessionState + Memory + System → BuiltContext
                                            ↓
                                      Context Builder

Semantic memory wiring:
  Before V2, ContextManager.inject_memories bypassed SemanticMemoryEngine
  (weighted 0.35 sim +0.25 recency+0.25 importance+0.15 confidence).
  This builder uses the engine when available, falling back to store.recall.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nally.context_builder")

@dataclass
class BuiltContext:
    """Exact context handed to the Reasoning Loop.

    `messages` is the final LLM-ready list (system + history + memory + scratchpad).
    `system_prompt` is the resolved active personality + platform + capability manifest.
    `memory_snippet` is the injected memory text (for tracing/verification).
    `session_snapshot` is a lightweight view of SessionState for debugging.
    `tool_schemas` holds the filtered tool schemas for this turn.
    `tokens_estimated` is the estimate after building.
    """
    messages: List[Dict[str, Any]] = field(default_factory=list)
    system_prompt: str = ""
    memory_snippet: str = ""
    conversation_summary: str = ""
    session_snapshot: Dict[str, Any] = field(default_factory=dict)
    tool_schemas: List[Dict[str, Any]] = field(default_factory=list)
    tokens_estimated: int = 0
    # Diagnostics
    pruned: bool = False
    compacted: bool = False
    memories_injected: int = 0


class ContextBuilder:
    """Typed, idempotent context construction. No side effects on caller args."""

    def build(
        self,
        messages: List[Dict[str, Any]],
        user_query: str,
        *,
        system_prompt: Optional[str] = None,
        session_id: str = "",
        route_key: str = "",
        interface: str = "",
        intent_class: str = "",
        max_tokens: Optional[int] = None,
         # dependencies injected for testability
        context_manager=None,
        memory_store=None,
        semantic_engine=None,
        tool_filter=None,
        registry=None,
    ) -> BuiltContext:
        """Build the complete context for one LLM turn.

        Args:
            messages: Conversation messages so far (including the new user turn with ts prefix).
            user_query: Raw user text for memory/tool filtering.
            system_prompt: Optional pre-resolved system prompt; built if None.
            session_id, route_key, interface: Session identity for snapshot.
            intent_class: Harness/Controller class for tool filtering.
            max_tokens: Override for CONTEXT_MAX_TOKENS.
            context_manager, memory_store, semantic_engine, tool_filter, registry:
                Optional injectables; resolved from singletons when None.

        Returns:
            BuiltContext with final messages, tool schemas, and diagnostics.
        """
        from ..config import CONTEXT_MAX_TOKENS

        cap = int(max_tokens) if max_tokens else CONTEXT_MAX_TOKENS

        # Resolve singletons lazily to avoid import cycles at module import time.
        if context_manager is None:
            from .context import context_manager as _cm
            context_manager = _cm
        if memory_store is None:
            from ..memory import memory_store as _ms
            memory_store = _ms
        if semantic_engine is None:
            try:
                from .semantic_memory import semantic_memory as _sem
                semantic_engine = _sem
            except Exception:
                semantic_engine = None

        # System prompt fallback
        if system_prompt is None:
            try:
                from ..config import get_system_prompt
                system_prompt = get_system_prompt(interface=interface or session_id)
            except Exception:
                system_prompt = ""

        # Copy messages shallowly — builder never mutates caller's evidence.
        msgs: List[Dict[str, Any]] = [dict(m) for m in messages]

        # ── 1. Prune ──
        pruned = False
        before_len = len(msgs)
        pruned_msgs = context_manager.prune(msgs, max_tokens=cap)
        if len(pruned_msgs) != before_len or context_manager.estimate_tokens(pruned_msgs) != context_manager.estimate_tokens(msgs):
            pruned = True
        msgs = pruned_msgs

        # ── 2. Compact ──
        compacted = False
        before_tokens = context_manager.estimate_tokens(msgs)
        compacted_msgs = context_manager.compact(msgs)
        if compacted_msgs is not msgs:
            compacted = True
        msgs = compacted_msgs

        # ── 3. Memory injection — authoritative semantic + engine ──
        memory_snippet = ""
        memories_injected = 0
        # Authoritative semantic patterns first (locked default) — never bypassed.
        authoritative_lines: List[str] = []
        try:
            _sem_hits = memory_store.recall_semantic(search=user_query, min_confidence=0.3) if memory_store else []
            for h in (_sem_hits or [])[:5]:
                pat = (h.get("pattern") or "").strip() if isinstance(h, dict) else ""
                if pat and all(pat not in ln for ln in authoritative_lines):
                    authoritative_lines.append(f"- [pattern] {pat}")
        except Exception as e:
            logger.debug(f"Authoritative semantic recall skipped: {e}")
        used_semantic = False
        if semantic_engine is not None:
            try:
                if not getattr(semantic_engine, "_memories", None):
                    try:
                        semantic_engine.hydrate_from_store(store=memory_store, limit=200)
                    except Exception:
                        pass
                recalled = []
                if getattr(semantic_engine, "_memories", None):
                    recalled = semantic_engine.recall(user_query, limit=12, min_confidence=0.3) or []
                if recalled or authoritative_lines:
                    lines = list(authoritative_lines)
                    lines += [f"- {m.key}: {m.value}" for m in recalled[:12] if f"- {m.key}: {m.value}" not in lines]
                    # High-priority project/auto_fact categorically (fixed: actually merge)
                    try:
                        for cat in ("project", "auto_fact"):
                            cat_mems = memory_store.recall(category=cat, min_confidence=0.5, limit=5)
                            if isinstance(cat_mems, dict):
                                for k, v in list(cat_mems.items())[:5]:
                                    line = f"- {k}: {v}"
                                    if line not in lines and len(lines) < 12:
                                        lines.append(line)
                    except Exception:
                        pass
                    memory_snippet = "\n".join(lines[:12])
                    # Inject as system message at the same position ContextManager uses
                    inject_idx = 1
                    for i, mm in enumerate(msgs):
                        if mm.get("role") == "user":
                            inject_idx = i
                            break
                    msgs.insert(inject_idx, {"role": "system", "content": f"[Relevant memories]\n{memory_snippet}"})
                    memories_injected = len(lines[:12])
                    used_semantic = True
            except Exception as e:
                logger.debug(f"Semantic recall fallback: {e}")
                used_semantic = False

        if not used_semantic:
            # Fallback: existing FTS/keyword/category logic in ContextManager
            before_inject = len(msgs)
            msgs = context_manager.inject_memories(user_query, msgs)
            memories_injected = len(msgs) - before_inject
            # Extract snippet that was injected (last memory insertion)
            for mm in msgs:
                if isinstance(mm.get("content"), str) and mm["content"].startswith("[Relevant memories]"):
                    memory_snippet = mm["content"][len("[Relevant memories]\n"):]
                    break

        # ── 4. Conversation history ──
        conversation_snippet = ""
        before_hist = len(msgs)
        msgs = context_manager.inject_conversation_history(msgs)
        if len(msgs) > before_hist:
            # History insertion is always at index 1; capture it
            for mm in msgs:
                c = mm.get("content", "")
                if isinstance(c, str) and ("Previous conversation" in c or "Conversation summary" in c or "Recent conversations" in c):
                    conversation_snippet = c
                    break

        # ── 5. Final safety prune if injections pushed us over budget ──
        estimated = context_manager.estimate_tokens(msgs)
        if estimated > cap:
            logger.warning(f"Context over limit after injections ({estimated} > {cap}), final prune")
            msgs = context_manager.prune(msgs, max_tokens=cap)
            pruned = True
            estimated = context_manager.estimate_tokens(msgs)

        # ── 6. Capability routing (V2 unified facade; falls back to legacy) ──
        tool_schemas: List[Dict[str, Any]] = []
        try:
            from ..tools.capability_router import capability_router as _cap
            task_class = intent_class or ""
            _decision = _cap.resolve(user_query, task_class=task_class)
            tool_schemas = _decision.schemas
        except Exception as e:
            logger.debug(f"CapabilityRouter fallback: {e}")
            try:
                if tool_filter is None:
                    from ..tools.filter import tool_filter as _tf
                    tool_filter = _tf
                if registry is None:
                    from ..tools.registry import registry as _reg
                    registry = _reg
                if not tool_filter._ready:
                    tool_filter.build_index(registry.tools)
                task_class = intent_class or ""
                tool_schemas = tool_filter.select(user_query, task_class=task_class)
            except Exception as e2:
                logger.debug(f"Tool filter fallback: {e2}")
                try:
                    from ..tools.registry import registry as _reg
                    tool_schemas = [t.to_openai_schema() for t in _reg.tools.values()]
                except Exception:
                    tool_schemas = []

        snapshot = {
            "session_id": session_id,
            "route_key": route_key,
            "interface": interface,
            "intent_class": intent_class,
            "message_count": len(msgs),
        }

        return BuiltContext(
            messages=msgs,
            system_prompt=system_prompt or "",
            memory_snippet=memory_snippet,
            conversation_summary=conversation_snippet,
            session_snapshot=snapshot,
            tool_schemas=tool_schemas,
            tokens_estimated=estimated,
            pruned=pruned,
            compacted=compacted,
            memories_injected=memories_injected,
        )


# Singleton
context_builder = ContextBuilder()
