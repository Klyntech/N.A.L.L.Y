"""Nally Controller — the harness around the model.

Owns the agent decision process that the leaked Fable/Opus/Codex prompts
implement implicitly.

Layers it unifies:
  INPUT (typed) → CONTEXT BUILDER → CLASSIFICATION → PLANNING JUDGE → ROUTE DECISION → EXECUTION GATE

Invariants (from the Nally V2 Architecture Map, approved 2026-09-12):
  - Fable 5.1 memory discipline + Opus verification/subagent patterns
  - Automatic judge: no user-facing toggle; controller decides DIRECT/LIGHT_PLAN/FULL_PLAN
  - High-stakes or irreversible work ALWAYS forces FULL PLAN + approval gate (Codex invariant)
  - Memory/Semantic, Verification, Response Composer, Output Router remain pluggable —
    controller only owns classification → judge → route → gate.

Light vs Full plan is a tier on top of Strategy.PLAN:
  - DIRECT  → no planning, instant/pattern or single-turn REACT
  - LIGHT   → 3-5 steps, bounded scope, auto-proceed after critique (no approval gate)
  - FULL    → ≤10 steps, dependencies/failure paths/verification explicit, mandatory approval
    when HIGH_STAKES or irreversible.

The existing TaskRouter owns Strategy DIRECT/REACT/PLAN/DELEGATE/ENGINEERING.
Controller extends it with a plan_tier + execution gate without changing the
router's external contract — RouteDecision gains optional fields that older
consumers ignore.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from .harness import Classification, TaskClass
from .task_router import RouteDecision, Strategy, route_from_classification

logger = logging.getLogger("nally.controller")

# ── Plan tier (overlay on Strategy.PLAN) ─────────────────

class PlanTier(str):
    NONE = "none"
    LIGHT = "light"
    FULL = "full"

# ── Signals ───────────────────────────────────────────────

_IRREVERSIBLE_PATTERNS = [
    r"\b(delete|remove|drop|destroy|wipe|erase)\b.*\b(database|table|production|server|volume|cluster|bucket)\b",
    r"\b(deploy|ship|release|publish|push to)\b.*\b(production|prod|live|main)\b",
    r"\b(migration|rollback|revert)\b",
    r"\brm\s+-rf\b",
    r"\bdrop\s+(table|database)\b",
    r"\btruncate\s+table\b",
    r"\bforce[-\s]*push\b",
    r"\bbilling|payment|invoice|charge\b.*\b(delete|refund|reverse)\b",
    r"\bsecurity\b.*\b(breach|rotate|revoke|disable)\b",
]

_DEPENDENCY_PATTERNS = [
    r"\b(then|after that|afterwards|next|finally|once .* done)\b",
    r"\b(depends on|requires|prerequisite|before .* can)\b",
    r"\b(first|second|third)\b.{0,60}\b(then|next)\b",
    r"\bstep\s*\d+\b",
]

_TOOL_HEAVY_KEYWORDS = (
    "build", "create", "implement", "scaffold", "generate", "deploy",
    "migrate", "configure", "install", "integrate", "connect", "fetch",
    "search", "analyze", "refactor", "write", "read file", "run",
)

_VERIFICATION_KEYWORDS = (
    "test", "verify", "validate", "deploy", "check", "ensure",
    "confirm", "lint", "proof", "review",
)

_CONTEXT_KEYWORDS = (
    "remember", "recall", "project", "previous", "earlier", "history",
    "memory", "conversation",
)


def _estimate_signals(text: str, classification: Optional[Classification]) -> Dict[str, Any]:
    """Cheap, deterministic signal extraction for the judge.

    No LLM call. All regex/keyword based so the judge remains fast and
    testable. Confidence comes from the classification itself.
    """
    lower = (text or "").lower()
    words = lower.split()
    word_count = len(words)
    sentence_count = lower.count(".") + lower.count("!") + lower.count("?") + lower.count("\n")
    # Step estimate: explicit steps > action verbs + conjunctions
    explicit_steps = len(re.findall(r"\b(step\s*\d+|phase\s*\d+|milestone)", lower))
    action_verbs = sum(1 for kw in _TOOL_HEAVY_KEYWORDS if kw in lower)
    conjunctions = len(re.findall(r"\b(and|then|also|plus|with|plus)\b", lower))
    comma_actions = len(re.findall(r"[,;].{5,}\b(build|create|deploy|configure|set up)\b", lower))

    step_count = explicit_steps
    if step_count == 0:
        # heuristic: each distinct action verb + conjunction-bound clause ~ one step
        step_count = min(max(action_verbs, conjunctions + 1, comma_actions + 1), 10)
        if "and then" in lower or "after that" in lower:
            step_count += 1

    tool_count = action_verbs

    uncertainty = 0.0
    if classification is not None:
        # Low confidence or AMBIGUOUS -> high uncertainty
        if getattr(classification, "task_class", None) in (TaskClass.AMBIGUOUS,):
            uncertainty = 0.7
        elif getattr(classification, "confidence", 1.0) < 0.6:
            uncertainty = 0.5
        elif getattr(classification, "task_class", None) == TaskClass.KNOWLEDGE:
            uncertainty = 0.3
    if re.search(r"\b(maybe|perhaps|unsure|either|or|option|alternativ)\b", lower):
        uncertainty = max(uncertainty, 0.6)

    dependencies = 0
    for pat in _DEPENDENCY_PATTERNS:
        if re.search(pat, lower):
            dependencies += 1
    if dependencies == 0 and step_count >= 3 and conjunctions >= 2:
        dependencies = 1  # implicit sequential deps

    irreversibility = 0
    for pat in _IRREVERSIBLE_PATTERNS:
        if re.search(pat, lower):
            irreversibility += 2  # heavy weight
            break
    # Destructive file_ops style also irreversible
    if re.search(r"\b(overwrite|replace|delete|remove)\b.*\b(file|folder|directory)\b", lower) and word_count < 80 and tool_count > 0:
        irreversibility = max(irreversibility, 1)

    context_req = 0
    for kw in _CONTEXT_KEYWORDS:
        if kw in lower:
            context_req += 1
    if re.search(r"\b(this|that|previous|earlier)\b.*\b(project|repo|code|conversation)\b", lower):
        context_req += 1

    verification_effort = 0
    for kw in _VERIFICATION_KEYWORDS:
        if kw in lower:
            verification_effort += 1
    if "deploy" in lower or "production" in lower:
        verification_effort = max(verification_effort, 2)

    high_stakes = False
    if classification is not None and getattr(classification, "task_class", None) == TaskClass.HIGH_STAKES:
        high_stakes = True
    if irreversibility >= 2:
        high_stakes = True
    if re.search(r"\b(production|billing|payment|security|credential|secret)\b", lower):
        # only high-stakes if paired with an action
        if tool_count > 0:
            high_stakes = True

    return {
        "step_count": int(step_count),
        "tool_count": int(tool_count),
        "uncertainty": float(min(uncertainty, 1.0)),
        "dependencies": int(min(dependencies, 3)),
        "irreversibility": int(irreversibility),
        "context_requirements": int(min(context_req, 3)),
        "verification_effort": int(min(verification_effort, 3)),
        "high_stakes": bool(high_stakes),
        "word_count": int(word_count),
        "sentence_count": int(sentence_count),
    }


def _decide_tier(signals: Dict[str, Any], task_class: str, route_strategy: Strategy) -> str:
    """Map signals + task class to plan tier.

    - trivial + reversible → LIGHT none (DIRECT/REACT path, no plan)
    - moderate → LIGHT
    - complex or high-stakes/irreversible → FULL
    """
    # High-stakes or irreversible always FULL (hard gate)
    if signals.get("high_stakes") or signals.get("irreversibility", 0) >= 2:
        return PlanTier.FULL

    cls = (task_class or "").upper()
    if cls in ("HIGH_STAKES",):
        return PlanTier.FULL
    if cls in ("COMPLEX",):
        # Moderate vs complex within COMPLEX
        sc = signals.get("step_count", 0)
        deps = signals.get("dependencies", 0)
        verif = signals.get("verification_effort", 0)
        tools = signals.get("tool_count", 0)
        # thresholds tuned to bias toward LIGHT for small COMPLEX tasks
        if sc >= 6 or deps >= 2 or verif >= 2 or tools >= 4:
            return PlanTier.FULL
        return PlanTier.LIGHT
    if cls in ("CREATIVE",):
        # creative rarely needs full planning; light only on explicit multi-step framing
        if signals.get("step_count", 0) >= 4 or signals.get("dependencies", 0) >= 1:
            return PlanTier.LIGHT
        return PlanTier.NONE
    if cls in ("SIMPLE", "KNOWLEDGE", "AMBIGUOUS"):
        # may still be LIGHT if strong multi-step signals
        if signals.get("step_count", 0) >= 4 or signals.get("dependencies", 0) >= 1:
            return PlanTier.LIGHT
        return PlanTier.NONE

    # fallback based purely on signals
    if signals.get("step_count", 0) >= 6:
        return PlanTier.FULL
    if signals.get("step_count", 0) >= 3:
        return PlanTier.LIGHT
    return PlanTier.NONE


@dataclass
class ControllerDecision:
    """Controller's authoritative decision for a turn.

    Wraps the TaskRouter's RouteDecision and adds judge outputs.
    Serializable via to_dict() for tracing and state threading.
    """

    route: RouteDecision
    tier: str = PlanTier.NONE  # none|light|full
    signals: Dict[str, Any] = field(default_factory=dict)
    requires_approval: bool = False
    max_steps: int = 0  # 0 = no plan
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = self.route.to_dict() if self.route else {}
        d.update(
            {
                "tier": self.tier,
                "signals": self.signals,
                "requires_approval": self.requires_approval,
                "max_steps": self.max_steps,
                "controller_reasoning": self.reasoning,
            }
        )
        return d


class NallyController:
    """Single decision boundary: Classification → Judge (tier) → Gate.

    Stateless per-request; thread-safe (no mutation beyond construction).

    Usage:
        controller = get_controller()
        decision = controller.decide(user_input, classification=_classification)
        # decision.route.strategy in {DIRECT, REACT, PLAN, ...}
        # decision.tier in {none, light, full}
        # decision.requires_approval bool
        # decision.max_steps hint for planner
    """

    # Light/Full step caps — mirror PLAN_MAX_STEPS default 10.
    # Overridable via config NALLY_PLAN_LIGHT_MAX_STEPS / NALLY_PLAN_MAX_STEPS.
    def __init__(self, light_cap: int | None = None, full_cap: int | None = None):
        if light_cap is not None:
            self._light_cap = int(light_cap)
        else:
            try:
                from ..config import NALLY_PLAN_LIGHT_MAX_STEPS as _light
                self._light_cap = int(_light)
            except Exception:
                self._light_cap = 5
        if full_cap is not None:
            self._full_cap = int(full_cap)
        else:
            try:
                from ..config import PLAN_MAX_STEPS as _full
                self._full_cap = int(_full)
            except Exception:
                self._full_cap = 10

    def decide(
        self,
        user_text: str,
        classification: Optional[Classification] = None,
        route_decision: Optional[RouteDecision] = None,
    ) -> ControllerDecision:
        """Produce a ControllerDecision for this request.

        Priority:
          1. If route_decision is already supplied (authoritative from core),
             re-derive only tier + gate (do not re-route).
          2. Else derive route via TaskRouter from classification + text,
             then judge tier and gate.
        """
        text = user_text or ""
        # ── Route (authoritative or derived) ──
        if route_decision is not None:
            route = route_decision
            cls = route.task_class or (classification.task_class.value if classification and hasattr(classification.task_class, "value") else "")
        else:
            # Derive via TaskRouter
            if classification is not None:
                route = route_from_classification(classification, user_text=text)
            else:
                # No classification yet — synthesize from text via harness fallback
                try:
                    from .harness import classify_intent
                    classification = classify_intent(text)
                except Exception:
                    classification = None
                route = route_from_classification(classification, user_text=text) if classification is not None else RouteDecision(strategy=Strategy.REACT, task_class="", confidence=0.0, reasoning="controller fallback", method="rules")

            cls = route.task_class or (classification.task_class.value if classification and hasattr(classification.task_class, "value") else "")

        signals = _estimate_signals(text, classification)

        # ── Tier ──
        # Only PLAN-capable strategies may carry a tier; DIRECT/REACT with a
        # tier would be contradictory.
        tier = PlanTier.NONE
        if route.strategy in (Strategy.PLAN, Strategy.ENGINEERING):
            tier = _decide_tier(signals, cls, route.strategy)
            # If judge says NONE but router said PLAN, preserve LIGHT as minimum —
            # router saw a task-class reason; judge may only downgrade within plan.
            if tier == PlanTier.NONE:
                tier = PlanTier.LIGHT
        else:
            # REACT/DIRECT but signals strong → may promote to plan (Codex-like).
            # Keep this narrow to avoid over-planning trivia.
            promoted = _decide_tier(signals, cls, route.strategy)
            if promoted != PlanTier.NONE and signals.get("step_count", 0) >= 4:
                # Promote via route mutation (single source of truth stays route)
                route = RouteDecision(
                    strategy=Strategy.PLAN,
                    task_class=cls or route.task_class,
                    confidence=max(route.confidence, 0.55),
                    reasoning=(route.reasoning + "; promoted by controller judge" if route.reasoning else "promoted by controller judge"),
                    method="hybrid",
                    pipeline=route.pipeline,
                )
                tier = promoted

        # ── Execution gate (hard invariant) ──
        requires_approval = False
        if tier == PlanTier.FULL and (signals.get("high_stakes") or signals.get("irreversibility", 0) >= 2):
            requires_approval = True
        # Also force FULL + approval when HIGH_STAKES even if tier had been LIGHT
        if cls.upper() == "HIGH_STAKES" or signals.get("high_stakes"):
            if tier != PlanTier.NONE:
                tier = PlanTier.FULL
            # HIGH_STAKES without a plan still requires an approval-shaped gate at
            # the tool layer — handled by permission gate, but mirror it here for visibility.
            if tier != PlanTier.NONE:
                requires_approval = True
            else:
                # No plan but still high-stakes → mark for tool-level gate
                requires_approval = False  # tool guardrails own it

        # ── Operational kill-switch ──
        # PLAN_ENABLED=false downgrades any plan to REACT (controller respects it).
        try:
            from ..config import PLAN_ENABLED
            if not PLAN_ENABLED and route.strategy in (Strategy.PLAN, Strategy.ENGINEERING):
                tier = PlanTier.NONE
                route = RouteDecision(
                    strategy=Strategy.REACT,
                    task_class=route.task_class,
                    confidence=route.confidence,
                    reasoning=route.reasoning + " (planning disabled by PLAN_ENABLED)",
                    method=route.method,
                    pipeline=route.pipeline,
                )
                requires_approval = False
        except Exception:
            pass

        # Config override for plan approval: NALLY_PLAN_REQUIRE_APPROVAL=high_stakes_only|all|none
        try:
            import os as _os
            _mode = _os.getenv("NALLY_PLAN_REQUIRE_APPROVAL", "high_stakes_only").strip().lower()
            if _mode == "all" and tier != PlanTier.NONE:
                requires_approval = True
            elif _mode == "none":
                requires_approval = False
            # high_stakes_only is default — already computed above
        except Exception:
            pass

        max_steps = 0
        if tier == PlanTier.LIGHT:
            max_steps = self._light_cap
        elif tier == PlanTier.FULL:
            max_steps = self._full_cap

        reasoning = (
            f"tier={tier} strategy={route.strategy.value if hasattr(route.strategy, 'value') else route.strategy} "
            f"class={cls or '-'} steps={signals['step_count']} tools={signals['tool_count']} deps={signals['dependencies']} "
            f"irrev={signals['irreversibility']} stakes={signals['high_stakes']}"
        )

        # Deterministic judge telemetry first (locked default): log full
        # signals so routing can be calibrated from evidence before any
        # LLM fallback is considered.
        logger.info(
            "Controller: tier=%s strategy=%s class=%s steps=%d tools=%d deps=%d "
            "irrev=%d stakes=%s unc=%.2f ctx=%d verif=%d gate=%s max_steps=%d (%s)",
            tier,
            route.strategy.value if hasattr(route.strategy, "value") else str(route.strategy),
            cls or "-",
            signals["step_count"],
            signals["tool_count"],
            signals["dependencies"],
            signals["irreversibility"],
            signals["high_stakes"],
            signals["uncertainty"],
            signals["context_requirements"],
            signals["verification_effort"],
            requires_approval,
            max_steps,
            route.method,
        )

        return ControllerDecision(
            route=route,
            tier=tier,
            signals=signals,
            requires_approval=requires_approval,
            max_steps=max_steps,
            reasoning=reasoning,
        )

    def should_delegate(self, user_text: str, signals: Optional[Dict[str, Any]] = None) -> bool:
        """Controller-owned subagent hint (V2 Phase 7).

        Deterministic parallel-work signals only — no LLM. The agent tool
        remains the execution mechanism, but the Controller owns the
        routing hint so parallel/specialized work flows through one
        decision surface. Single-agent loop stays default.
        """
        text = (user_text or "").lower()
        sig = signals or {}
        # Explicit parallel framing
        if re.search(r"\b(in parallel|simultaneously|at the same time|each of|spawn)\b", text):
            return True
        # Numbered multi-task framing with independent clauses
        if len(re.findall(r"\b(step\s*\d+|task\s*\d+|first|second|third)\b", text)) >= 2:
            if sig.get("step_count", 0) >= 3 or text.count(" and ") >= 2:
                return True
        return False

    def classify_and_decide(self, user_text: str, llm_call_fn=None) -> tuple[Optional[Classification], ControllerDecision]:
        """Convenience: classify via harness then decide."""
        try:
            from .harness import classify_intent
            classification = classify_intent(user_text, llm_call_fn=llm_call_fn)
        except Exception as e:
            logger.warning(f"Controller classify failed: {e}")
            classification = None
        decision = self.decide(user_text, classification=classification)
        return classification, decision


# ── Singleton ─────────────────────────────────────────────
# NallyController is stateless after __init__ (no mutation, no request-scoped
# state). Multiple threads safely share one instance without locking — the
# double-checked locking pattern used by NallyAgent/ToolRegistry is unnecessary
# here because there is no intermediate partially-constructed state to guard.

_controller: Optional[NallyController] = None

def get_controller() -> NallyController:
    global _controller
    if _controller is None:
        _controller = NallyController()
    return _controller
