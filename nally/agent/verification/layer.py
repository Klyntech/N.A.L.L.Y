"""Verification Layer — single authoritative façade (V2).

Wires the four previously separate check sites behind one deterministic
call in the hot path (no LLM):

  1. ClaimVerifier (tool-bypass / fabricated limits / hallucinated tool)
  2. Receipt-based honesty (success vs display)
  3. Completion gate (tool_failures/partial vs success claim)
  4. Output guardrails (sensitive_data / honesty / etc., warn vs block)

The aggregated result decides PASS (respond) vs FAIL (corrective reasoning).

Design goals (from Fable "report what actually happened" + Opus verifier):
  - Keep hot path deterministic — LLM self-correction is triggered by this
    layer but is not part of the layer itself.
  - One trace span per turn, one structured result for response_composer.
  - Tolerate partial success: only block when failures dominate or all failed.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nally.verification.layer")

@dataclass
class VerificationTurnResult:
    """Turn-level verification outcome returned to graph/response_composer."""

    is_honest: bool
    should_correct: bool  # True when self-correction injection is warranted
    should_block: bool    # True when completion gate says TASK NOT COMPLETE
    trust_score: float
    # Flattened findings from the underlying ClaimVerifier for tracing
    findings: List[Dict[str, Any]] = field(default_factory=list)
    unsupported: int = 0
    contradicted: int = 0
    backed: int = 0
    # Guardrail signals
    guardrail_blocked: bool = False
    guardrail_warnings: List[str] = field(default_factory=list)
    # Gate signals
    partial_reason: str = ""
    failed_tools: List[str] = field(default_factory=list)
    # Budget signals (informational only — never block completion)
    budget_warning: str = ""
    budget_remaining: float = 0.0
    # Human-readable correction prompt (when should_correct)
    correction_prompt: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_honest": self.is_honest,
            "should_correct": self.should_correct,
            "should_block": self.should_block,
            "trust_score": self.trust_score,
            "unsupported": self.unsupported,
            "contradicted": self.contradicted,
            "backed": self.backed,
            "guardrail_blocked": self.guardrail_blocked,
            "guardrail_warnings": self.guardrail_warnings,
            "partial_reason": self.partial_reason,
            "failed_tools": self.failed_tools,
            "budget_warning": self.budget_warning,
            "budget_remaining": self.budget_remaining,
            "findings": self.findings,
        }

# ── Partial completion gate (factored out of graph.py) ─────

def _partial_reason(
    tool_failures: List[Dict[str, Any]],
    task_progress: Dict[str, str],
    start_time: float = 0.0,
    wall_budget: int = 0,
    tool_calls_total: int = 0,
) -> str:
    """Deterministic partial gate — return reason string or ''.

    Blocks ONLY when tool failures dominate (all tracked tools failed, or
    >50% failed). Wall-clock budget NEVER decides completion — elapsed time
    produces an informational budget WARNING (see _budget_warning), not a
    block. ``start_time``/``wall_budget``/``tool_calls_total`` are kept as
    backward-compat params and ignored for blocking.
    """
    failed = [t for t, s in (task_progress or {}).items() if s == "failed"]
    succeeded = [t for t, s in (task_progress or {}).items() if s == "success"]
    total_tracked = len(failed) + len(succeeded)
    if failed:
        if total_tracked == 0 or len(failed) >= total_tracked or (total_tracked and len(failed) / total_tracked > 0.5):
            return f"tool failures: {', '.join(failed)}"
    return ""


def _budget_warning(
    start_time: float = 0.0,
    wall_budget: int = 0,
    warn_threshold: float = 0.8,
    now: float | None = None,
) -> Tuple[str, float]:
    """Informational budget warning — never a completion signal.

    Returns (warning_message, remaining_seconds). Empty message when the
    warn threshold has not been crossed or inputs are invalid. Uses
    time.monotonic() to match ExecutionBudget (deadline authoritative).
    """
    try:
        limit = float(wall_budget or 0)
        raw_start = float(start_time or 0.0)
        if not raw_start or limit <= 0:
            return "", 0.0
        try:
            from ..budget import normalize_start_to_monotonic
            start = normalize_start_to_monotonic(raw_start)
        except Exception:
            start = raw_start
        threshold = float(warn_threshold or 0.8)
        current = now if now is not None else time.monotonic()
        elapsed = max(0.0, current - start)
        remaining = max(0.0, (start + limit) - current)
        if elapsed >= limit * threshold:
            return (
                f"budget {int(elapsed)}s/{int(limit)}s "
                f"(>{int(threshold * 100)}% consumed, {int(remaining)}s remaining)",
                remaining,
            )
    except Exception:
        pass
    return "", 0.0

# ── Facade ──────────────────────────────────────────────────

class VerificationLayer:
    """Deterministic turn-level verifier. No LLM in hot path."""

    def verify_turn(
        self,
        response: str,
        *,
        receipts: Optional[List[Any]] = None,
        registered_tools: Optional[set] = None,
        tool_failures: Optional[List[Dict[str, Any]]] = None,
        task_progress: Optional[Dict[str, str]] = None,
        start_time: float = 0.0,
        wall_budget: int = 0,
        tool_calls_total: int = 0,
    ) -> VerificationTurnResult:
        """Run all verification checks for a turn's final response.

        Returns a structured result that graph.llm_call consumes:
          - should_block → completion gate forces [TASK NOT COMPLETE]
          - should_correct → feed VERIFICATION FAILED to LLM for one rewrite
          - is_honest → overall honest flag
        """
        receipts = receipts or []
        tool_failures = tool_failures or []
        task_progress = task_progress or {}

        findings: List[Dict[str, Any]] = []
        unsupported = 0
        contradicted = 0
        backed = 0
        trust = 1.0

        # 1) Claim verifier (if receipts exist — skip when no tools called)
        correction_lines: List[str] = []
        if receipts:
            try:
                from ..verifier import claim_verifier
                vresult = claim_verifier.verify(response or "", receipts, registered_tools or set())
                unsupported = int(vresult.unsupported_count)
                contradicted = int(vresult.contradicted_count)
                backed = int(vresult.backed_count)
                trust = float(vresult.trust_score)
                for f in vresult.findings:
                    findings.append(f.to_dict() if hasattr(f, "to_dict") else dict(f))
                    if getattr(f, "verdict", None) and getattr(f.verdict, "value", "") in ("unsupported", "contradicted"):
                        correction_lines.append(f"- [{f.verdict.value}] {f.claim}: {f.evidence}")
            except Exception as e:
                logger.debug(f"Claim verifier skipped: {e}")

        # 2) Guardrails — run without blocking on warn; expose block flag
        guardrail_blocked = False
        guardrail_warnings: List[str] = []
        try:
            from ..guardrails import guardrail_engine
            failed_names = [f.get("tool") for f in tool_failures if f.get("tool")]
            greceipts = receipts
            # guardrail_engine.check_output expects context with receipts + failed_tools
            g_results = guardrail_engine.check_output(
                response or "",
                context={"receipts": greceipts, "failed_tools": failed_names},
            )
            if guardrail_engine.should_block(g_results):
                guardrail_blocked = True
                for r in g_results:
                    if r.verdict.value == "block":
                        guardrail_warnings.append(r.message)
                        break
            else:
                for r in g_results:
                    if r.verdict.value == "warn":
                        guardrail_warnings.append(r.message)
        except Exception as e:
            logger.debug(f"Guardrail layer skipped: {e}")

        # 3) Completion gate — failure dominance ONLY. Wall-clock budget
        # never blocks: it produces budget_warning (informational).
        partial = _partial_reason(tool_failures, task_progress, start_time, wall_budget, tool_calls_total)
        try:
            from ...config import BUDGET_WARN_THRESHOLD as _warn_thr
        except Exception:
            _warn_thr = 0.8
        budget_warning, budget_remaining = _budget_warning(
            start_time, wall_budget, _warn_thr
        )
        should_block = False
        # Mirror graph logic: block when partial reason or failure dominance
        failure_count = len(tool_failures)
        if partial:
            should_block = True
        elif failure_count and tool_calls_total:
            should_block = failure_count >= tool_calls_total or (failure_count / tool_calls_total) > 0.5
        elif failure_count and tool_calls_total == 0:
            should_block = True

        # Overall honesty: unsupported/contradicted or guardrail block
        is_honest = (contradicted == 0 and unsupported == 0) and not guardrail_blocked

        # When should we inject a correction rewrite?
        # - claim contradictions/unsupported always warrant a rewrite attempt
        # - guardrail warn alone does not trigger rewrite (composer may modify)
        should_correct = (contradicted > 0 or unsupported > 0) and not should_block

        correction_prompt = ""
        if should_correct and correction_lines:
            correction_prompt = (
                "VERIFICATION FAILED — your last response contained unsupported claims:\n"
                + "\n".join(correction_lines[:6])
                + "\n\nRewrite your response. Remove or correct any claims not backed by receipts. "
                  "If you did not call a tool, do not claim you did. "
                  "If a tool failed, say it failed. Do not invent numbers or limits."
            )

        failed_tool_names = [f.get("tool", "") for f in tool_failures]

        return VerificationTurnResult(
            is_honest=is_honest,
            should_correct=should_correct,
            should_block=should_block,
            trust_score=trust,
            findings=findings,
            unsupported=unsupported,
            contradicted=contradicted,
            backed=backed,
            guardrail_blocked=guardrail_blocked,
            guardrail_warnings=guardrail_warnings,
            partial_reason=partial,
            failed_tools=failed_tool_names,
            budget_warning=budget_warning,
            budget_remaining=budget_remaining,
            correction_prompt=correction_prompt,
        )


# Singleton for direct import
verification_layer = VerificationLayer()

def verify_turn(
    response: str,
    receipts: Optional[List[Any]] = None,
    registered_tools: Optional[set] = None,
    tool_failures: Optional[List[Dict[str, Any]]] = None,
    task_progress: Optional[Dict[str, str]] = None,
    start_time: float = 0.0,
    wall_budget: int = 0,
    tool_calls_total: int = 0,
) -> VerificationTurnResult:
    """Functional shorthand for VerificationLayer.verify_turn."""
    return verification_layer.verify_turn(
        response,
        receipts=receipts,
        registered_tools=registered_tools,
        tool_failures=tool_failures,
        task_progress=task_progress,
        start_time=start_time,
        wall_budget=wall_budget,
        tool_calls_total=tool_calls_total,
    )
