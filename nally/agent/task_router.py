"""TaskRouter — single decision boundary for how N.A.L.L.Y executes a request.

User request
    ↓
Harness / cheap classification (optional, preferred)
    ↓
TaskRouter
    ↓
DIRECT | REACT | PLAN | DELEGATE | ENGINEERING
    ↓
Graph / execution

Planning is automatic for ordinary use. PLAN_ENABLED remains only as an
operational kill-switch (force-disable planning for a deployment). Users
and operators do not need to toggle "planning mode" for normal tasks.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("nally.task_router")


class Strategy(str, Enum):
    """Canonical execution strategies.

    Lifecycle: a strategy is a temporary per-request execution mode, not a
    permanent mode. Each request gets ONE routing decision; the graph
    consumes it and exits (via synthesize/END) when verification succeeds.
    """

    DIRECT = "direct"  # Instant answer / pattern matcher path (pre-graph, wired in core.process)
    REACT = "react"  # Default tool-using loop
    PLAN = "plan"  # Plan → execute → verify (temporary, exits on sufficient verification)
    DELEGATE = "delegate"  # Reserved: delegation is currently an LLM-invoked tool capability (subagent/), not a router branch
    ENGINEERING = "engineering"  # Conversational alias of PLAN; full loop is CLI --engineer bypass (main.py)


@dataclass
class RouteDecision:
    """Outcome of the task router."""

    strategy: Strategy
    task_class: str = ""
    confidence: float = 0.0
    reasoning: str = ""
    method: str = "rules"  # rules | harness | hybrid
    pipeline: Optional[Dict[str, bool]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy.value,
            "task_class": self.task_class,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "method": self.method,
            "pipeline": self.pipeline,
        }

    @property
    def needs_plan(self) -> bool:
        return self.strategy in (Strategy.PLAN, Strategy.ENGINEERING)


# ── TaskClass → default strategy ─────────────────────────────────────────────

_CLASS_TO_STRATEGY = {
    "SIMPLE": Strategy.REACT,
    "KNOWLEDGE": Strategy.REACT,
    "AMBIGUOUS": Strategy.REACT,
    "CREATIVE": Strategy.REACT,  # critique may still run via harness pipeline
    "COMPLEX": Strategy.PLAN,
    "HIGH_STAKES": Strategy.PLAN,
}

# Strong engineering signals (large coding / build work)
_ENGINEERING_PATTERNS = [
    r"\b(refactor|rewrite|redesign)\b.{0,60}\b(codebase|module|system|architecture)\b",
    r"\b(implement|build|scaffold)\b.{0,40}\b(full|entire|complete)\b.{0,40}\b(app|service|feature|api)\b",
    r"\b(migrate|port)\b.{0,30}\b(database|schema|backend|frontend)\b",
    r"\bend[- ]to[- ]end\b.{0,20}\b(test|implement|build)\b",
    r"\b(entire|whole)\b.{0,20}\b(codebase|architecture)\b",
]

# Explicit multi-step plan signals (supplement when harness is weak/absent)
_PLAN_SIGNALS = [
    r"\b(step[- ]by[- ]step|multi[- ]step|break (it|this) down)\b",
    r"\b(plan|roadmap|phases?)\b.{0,20}\b(then|and then|after that)\b",
    r"\b(first|second|third|finally)\b.+\b(then|next|after)\b",
]


def _detect_engineering(text: str) -> bool:
    lower = (text or "").lower()
    if len(lower.split()) < 8:
        return False
    return any(re.search(p, lower) for p in _ENGINEERING_PATTERNS)


def _detect_plan_signals(text: str) -> bool:
    lower = (text or "").lower()
    hits = sum(1 for p in _PLAN_SIGNALS if re.search(p, lower))
    # Long multi-sentence action requests also lean plan
    sentences = lower.count(".") + lower.count("!") + lower.count("?")
    action_kw = ("build", "create", "deploy", "migrate", "configure", "implement", "set up", "setup")
    has_action = any(kw in lower for kw in action_kw)
    if hits >= 1:
        return True
    if sentences >= 3 and has_action and len(lower.split()) >= 40:
        return True
    return False


def route_from_classification(
    classification: Any,
    user_text: str = "",
) -> RouteDecision:
    """Map a harness Classification (or compatible object) to a Strategy.

    Does not call an LLM. Cheap and deterministic given the classification.
    """
    task_class = ""
    confidence = 0.0
    reasoning = ""
    method = "rules"

    if classification is not None:
        tc = getattr(classification, "task_class", None)
        if tc is not None:
            task_class = tc.value if hasattr(tc, "value") else str(tc)
        confidence = float(getattr(classification, "confidence", 0.0) or 0.0)
        reasoning = str(getattr(classification, "reasoning", "") or "")
        method = str(getattr(classification, "method", "harness") or "harness")

    # Engineering override (reserved path; currently still executed via PLAN graph)
    if _detect_engineering(user_text):
        return RouteDecision(
            strategy=Strategy.ENGINEERING,
            task_class=task_class or "COMPLEX",
            confidence=max(confidence, 0.7),
            reasoning=reasoning or "engineering signals in request",
            method="hybrid" if task_class else "rules",
        )

    strategy = _CLASS_TO_STRATEGY.get(task_class.upper(), Strategy.REACT) if task_class else Strategy.REACT

    # If harness said simple but strong multi-step signals exist, promote to PLAN
    if strategy == Strategy.REACT and _detect_plan_signals(user_text):
        strategy = Strategy.PLAN
        method = "hybrid"
        reasoning = (reasoning + "; " if reasoning else "") + "multi-step plan signals"

    pipeline = None
    try:
        from .harness import TaskClass, get_pipeline_config

        if task_class:
            cfg = get_pipeline_config(TaskClass(task_class))
            pipeline = {
                "direct_answer": cfg.direct_answer,
                "critique": cfg.critique,
                "scratchpad": cfg.scratchpad,
                "tool_verify": cfg.tool_verify,
            }
    except Exception:
        pass

    return RouteDecision(
        strategy=strategy,
        task_class=task_class,
        confidence=confidence,
        reasoning=reasoning or f"mapped {task_class or 'unknown'} → {strategy.value}",
        method=method,
        pipeline=pipeline,
    )


def route(
    user_text: str,
    classification: Any = None,
    llm_call_fn: Optional[Callable] = None,
    force_classify: bool = False,
) -> RouteDecision:
    """Full routing entry point.

    Prefer an existing harness classification. Optionally run classify_intent
    if none is provided and force_classify is True / llm_call_fn is given.
    """
    if classification is None and (force_classify or llm_call_fn is not None):
        try:
            from .harness import classify_intent

            classification = classify_intent(user_text, llm_call_fn=llm_call_fn)
        except Exception as e:
            logger.debug("TaskRouter: classify_intent failed: %s", e)

    decision = route_from_classification(classification, user_text=user_text)

    # Operational kill-switch: PLAN_ENABLED=false forces REACT even for COMPLEX
    try:
        from ..config import PLAN_ENABLED

        if not PLAN_ENABLED and decision.needs_plan:
            logger.info(
                "TaskRouter: PLAN_ENABLED=false; downgrading %s → REACT",
                decision.strategy.value,
            )
            decision = RouteDecision(
                strategy=Strategy.REACT,
                task_class=decision.task_class,
                confidence=decision.confidence,
                reasoning=decision.reasoning + " (planning disabled by PLAN_ENABLED)",
                method=decision.method,
                pipeline=decision.pipeline,
            )
    except Exception:
        pass

    logger.info(
        "TaskRouter: strategy=%s class=%s conf=%.2f method=%s",
        decision.strategy.value,
        decision.task_class or "-",
        decision.confidence,
        decision.method,
    )
    return decision


def strategy_to_plan_status(decision: RouteDecision) -> str:
    """Map router decision to graph plan_status used by route_after_classify."""
    if decision.needs_plan:
        return "planning"
    return "none"
