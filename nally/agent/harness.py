"""Nally Harness — intent classification, pipeline routing, and critique.

Phase 1: IntentClassifier that categorizes user requests into one of six
task classes and determines which pipeline stages should run.

Phase 2: Generate→Critique→Revise pipeline for COMPLEX and CREATIVE classes.

The classifier is a single cheap LLM call (or regex fallback), not the
same expensive model used for the actual task.

Every stage is independently disable-able via config feature flags.
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nally.harness")


# ── Task Classes ──────────────────────────────────────────

class TaskClass(str, Enum):
    """Fixed enum of task classifications."""
    SIMPLE = "SIMPLE"
    KNOWLEDGE = "KNOWLEDGE"
    CREATIVE = "CREATIVE"
    COMPLEX = "COMPLEX"
    AMBIGUOUS = "AMBIGUOUS"
    HIGH_STAKES = "HIGH_STAKES"


@dataclass
class Classification:
    """Structured output from the intent classifier."""
    task_class: TaskClass
    confidence: float
    reasoning: str
    method: str = "llm"  # "llm" or "regex"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_class": self.task_class.value,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "method": self.method,
        }


@dataclass
class PipelineConfig:
    """Which stages are enabled for a given task class."""
    direct_answer: bool = True
    critique: bool = False
    scratchpad: bool = False
    tool_verify: bool = False


# ── Default Pipeline Configs ──────────────────────────────

DEFAULT_PIPELINES: Dict[TaskClass, PipelineConfig] = {
    TaskClass.SIMPLE: PipelineConfig(
        direct_answer=True, critique=False, scratchpad=False, tool_verify=False,
    ),
    TaskClass.KNOWLEDGE: PipelineConfig(
        direct_answer=True, critique=False, scratchpad=False, tool_verify=False,
    ),
    TaskClass.CREATIVE: PipelineConfig(
        direct_answer=False, critique=True, scratchpad=False, tool_verify=False,
    ),
    TaskClass.COMPLEX: PipelineConfig(
        direct_answer=False, critique=True, scratchpad=True, tool_verify=True,
    ),
    TaskClass.AMBIGUOUS: PipelineConfig(
        direct_answer=True, critique=False, scratchpad=False, tool_verify=False,
    ),
    TaskClass.HIGH_STAKES: PipelineConfig(
        direct_answer=False, critique=True, scratchpad=True, tool_verify=True,
    ),
}


# ── Regex Heuristics (fast fallback) ──────────────────────

_SIMPLE_PATTERNS = [
    r"^(hey|hi|hello|thanks|ok|yes|no|lol|haha)\b",
    r"^(who (am i|are you)|what('s| is) your)",
    r"^(remember|recall|forget)\b",
    r"^(what|how|why|when|where|who)\s+\S{0,20}\??$",
]

_CREATIVE_SIGNALS = [
    r"\b(write|draft|compose|create a story|poem|essay|blog post)\b",
    r"\b(design|imagine|brainstorm|ideate)\b",
    r"\b(refactor|rewrite|reimagine)\b.*\b(code|prose|text)\b",
]

_HIGH_STAKES_SIGNALS = [
    r"\b(deploy|production|ship|release|push to)\b",
    r"\b(delete|remove|drop|destroy|wipe)\b.*\b(database|table|production|server)\b",
    r"\b(migration|rollback|revert)\b",
    r"\b(security|vulnerability|breach|auth)\b",
    r"\b(billing|payment|financial|invoice)\b",
]

_COMPLEX_SIGNALS = [
    r"\b(implement|build|create|set up|configure|install)\b",
    r"\b(multiple|several|many|all of)\b",
    r"\b(step.by.step|plan|organize|orchestrat)\b",
    r"\b(integrate|connect|wire|link)\b.*\b(with|to|and)\b",
    r"\b(migrate|upgrade|refactor)\b",
]

_KNOWLEDGE_SIGNALS = [
    r"^(what|how|why|when|where|who)\s",
    r"^(explain|tell me about|define|describe)\b",
    r"\b(difference between|compare|versus|vs\.?)\b",
    r"\b(why does|why do|how does|how do)\b",
]


def _classify_regex(text: str) -> Classification:
    """Fast regex-based classification. Returns a Classification with method='regex'.

    Order: high-stakes > creative > knowledge > complex > simple > ambiguous.
    High-stakes is checked first because it's the most specific and dangerous.
    """
    text_lower = text.lower().strip()
    word_count = len(text.split())
    sentence_count = text.count(".") + text.count("!") + text.count("?")
    action_keywords = ("build", "create", "deploy", "migrate", "set up", "setup",
                       "configure", "install", "implement", "integrate", "delete",
                       "remove", "drop", "destroy", "wipe")
    has_action = any(kw in text_lower for kw in action_keywords)

    # 1. High-stakes signals (most specific — check first)
    high_stakes_score = sum(1 for pat in _HIGH_STAKES_SIGNALS if re.search(pat, text_lower))
    if high_stakes_score >= 1:
        return Classification(
            task_class=TaskClass.HIGH_STAKES,
            confidence=0.75,
            reasoning=f"Regex: matched {high_stakes_score} high-stakes signal(s)",
            method="regex",
        )

    # 2. Creative signals
    creative_score = sum(1 for pat in _CREATIVE_SIGNALS if re.search(pat, text_lower))
    if creative_score >= 1:
        return Classification(
            task_class=TaskClass.CREATIVE,
            confidence=0.7,
            reasoning=f"Regex: matched {creative_score} creative signal(s)",
            method="regex",
        )

    # 3. Knowledge signals (only if no action keywords)
    knowledge_score = sum(1 for pat in _KNOWLEDGE_SIGNALS if re.search(pat, text_lower))
    if knowledge_score >= 1 and not has_action:
        return Classification(
            task_class=TaskClass.KNOWLEDGE,
            confidence=0.7,
            reasoning=f"Regex: matched {knowledge_score} knowledge signal(s)",
            method="regex",
        )

    # 4. Complex signals
    complex_score = sum(1 for pat in _COMPLEX_SIGNALS if re.search(pat, text_lower))
    if sentence_count >= 3:
        complex_score += 1
    if has_action:
        complex_score += 1
    if complex_score >= 2:
        return Classification(
            task_class=TaskClass.COMPLEX,
            confidence=0.65,
            reasoning=f"Regex: matched {complex_score} complex signal(s)",
            method="regex",
        )

    # 5. Simple signals (greetings, short questions)
    for pat in _SIMPLE_PATTERNS:
        if re.search(pat, text_lower):
            return Classification(
                task_class=TaskClass.SIMPLE,
                confidence=0.8,
                reasoning="Regex: matched simple signal pattern",
                method="regex",
            )

    # Short queries without action keywords → simple
    if word_count < 30 and not has_action and sentence_count < 2:
        return Classification(
            task_class=TaskClass.SIMPLE,
            confidence=0.7,
            reasoning="Regex: short query without action keywords",
            method="regex",
        )

    # 6. Default: ambiguous
    return Classification(
        task_class=TaskClass.AMBIGUOUS,
        confidence=0.5,
        reasoning="Regex: no strong signals matched",
        method="regex",
    )


# ── LLM-based Classification ─────────────────────────────

_CLASSIFICATION_PROMPT = """Classify this user request into exactly one task class.

TASK CLASSES:
- SIMPLE: Greetings, quick factual questions, simple commands, short answers suffice.
- KNOWLEDGE: Explanations, comparisons, "how does X work", research questions. Needs accurate info but no creation.
- CREATIVE: Writing, drafting, storytelling, code authoring, design ideation. Needs original output.
- COMPLEX: Multi-step tasks, builds, deployments, integrations, migrations. Needs planning and tool use.
- AMBIGUOUS: Unclear intent, could be multiple classes, needs clarification or best-guess routing.
- HIGH_STAKES: Production changes, deletions, security, billing, financial. Extra caution required.

REQUEST: {request}

OUTPUT FORMAT (JSON only, no explanation outside JSON):
{{"class": "CLASS_NAME", "confidence": 0.0-1.0, "reasoning": "one sentence explaining why"}}

Output ONLY the JSON object."""


def classify_by_llm(text: str, llm_call_fn) -> Classification:
    """Classify using a cheap LLM call.

    Args:
        text: The user's request text.
        llm_call_fn: A callable that takes (messages, temperature) and returns a string.
                     Should be a cheap/fast model, not the main agent model.

    Returns:
        Classification with method='llm'.
    """
    prompt = _CLASSIFICATION_PROMPT.format(request=text[:2000])

    try:
        response = llm_call_fn(
            messages=[
                {"role": "system", "content": "You are an intent classifier. Output only valid JSON."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )

        # Parse JSON response
        start = response.find("{")
        end = response.rfind("}") + 1
        if start == -1 or end <= start:
            logger.warning("LLM classifier returned non-JSON, falling back to regex")
            return _classify_regex(text)

        data = json.loads(response[start:end])
        class_str = data.get("class", "").upper()

        try:
            task_class = TaskClass(class_str)
        except ValueError:
            logger.warning(f"LLM classifier returned unknown class: {class_str}")
            return _classify_regex(text)

        return Classification(
            task_class=task_class,
            confidence=float(data.get("confidence", 0.7)),
            reasoning=data.get("reasoning", "LLM classification"),
            method="llm",
        )

    except Exception as e:
        logger.warning(f"LLM classification failed: {e}, falling back to regex")
        return _classify_regex(text)


# ── Public API ────────────────────────────────────────────

def classify_intent(
    text: str,
    llm_call_fn=None,
    override: Optional[str] = None,
) -> Classification:
    """Classify a user request into a task class.

    Args:
        text: The user's request text.
        llm_call_fn: Optional LLM callable for classification. If None, uses regex only.
        override: Manual override class name (bypasses classification).

    Returns:
        Classification with task_class, confidence, reasoning.
    """
    # Manual override
    if override:
        override_upper = override.upper()
        try:
            task_class = TaskClass(override_upper)
            return Classification(
                task_class=task_class,
                confidence=1.0,
                reasoning=f"Manual override: {override}",
                method="override",
            )
        except ValueError:
            logger.warning(f"Invalid override class: {override}, classifying normally")

    # LLM classification (preferred)
    if llm_call_fn:
        return classify_by_llm(text, llm_call_fn)

    # Regex fallback
    return _classify_regex(text)


def get_pipeline_config(task_class: TaskClass) -> PipelineConfig:
    """Get the pipeline configuration for a task class."""
    from ..config import HARNESS_PIPELINES

    config_dict = HARNESS_PIPELINES.get(task_class.value, {})
    defaults = DEFAULT_PIPELINES.get(task_class, PipelineConfig())
    return PipelineConfig(
        direct_answer=config_dict.get("direct_answer", defaults.direct_answer),
        critique=config_dict.get("critique", defaults.critique),
        scratchpad=config_dict.get("scratchpad", defaults.scratchpad),
        tool_verify=config_dict.get("tool_verify", defaults.tool_verify),
    )


# ── Phase 2: Generate→Critique→Revise ────────────────────

# Rubrics per task class — specific evaluation criteria, not generic "find problems"
CRITIQUE_RUBRICS: Dict[TaskClass, str] = {
    TaskClass.COMPLEX: (
        "Evaluate this response for a complex multi-step task:\n"
        "1. ACCURACY: Are technical claims correct? Are tool names, APIs, parameters accurate?\n"
        "2. COMPLETENESS: Does it address all parts of the request?\n"
        "3. ORDERING: Are steps in logical execution order?\n"
        "4. DEPENDENCIES: Are step dependencies correct (no use before definition)?\n"
        "5. EDGE CASES: Are failure modes and error handling addressed?\n"
        "6. FEASIBILITY: Can this actually be executed with the available tools?"
    ),
    TaskClass.CREATIVE: (
        "Evaluate this creative response:\n"
        "1. ORIGINALITY: Is the content fresh, or generic/templated?\n"
        "2. COHERENCE: Does the piece flow logically and maintain internal consistency?\n"
        "3. VOICE: Is the tone appropriate and consistent throughout?\n"
        "4. DEPTH: Does it go beyond surface-level, or is it shallow?\n"
        "5. COMPLETENESS: Does it fulfill the full creative brief?\n"
        "6. ENGAGEMENT: Would the reader find this compelling?"
    ),
}

# Max critique revisions per request (configurable via env)
_MAX_CRITIQUE_REVISIONS = 1


@dataclass
class CritiqueResult:
    """Structured output from the critique call."""
    issues: List[str] = field(default_factory=list)
    severity: str = "none"  # "none", "low", "medium", "high"
    should_revise: bool = False
    raw_response: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "issues": self.issues,
            "severity": self.severity,
            "should_revise": self.should_revise,
        }


@dataclass
class CritiquePipelineResult:
    """Result of a full generate→critique→revise pipeline."""
    response: str
    was_revised: bool
    critique: Optional[CritiqueResult]
    cost_tokens: int = 0
    cost_latency_ms: float = 0.0
    stages_fired: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "response": self.response,
            "was_revised": self.was_revised,
            "critique": self.critique.to_dict() if self.critique else None,
            "cost_tokens": self.cost_tokens,
            "cost_latency_ms": self.cost_latency_ms,
            "stages_fired": self.stages_fired,
        }


def _parse_critique_response(response: str) -> CritiqueResult:
    """Parse critique LLM response into structured CritiqueResult."""
    try:
        start = response.find("{")
        end = response.rfind("}") + 1
        if start == -1 or end <= start:
            return CritiqueResult(raw_response=response)

        data = json.loads(response[start:end])
        issues = data.get("issues", [])
        if isinstance(issues, str):
            issues = [issues] if issues else []

        severity = data.get("severity", "none").lower()
        if severity not in ("none", "low", "medium", "high"):
            severity = "none"

        should_revise = data.get("should_revise", False)
        if isinstance(should_revise, str):
            should_revise = should_revise.lower() in ("true", "yes", "1")

        return CritiqueResult(
            issues=issues,
            severity=severity,
            should_revise=should_revise,
            raw_response=response,
        )
    except (json.JSONDecodeError, ValueError):
        return CritiqueResult(raw_response=response)


def run_critique_pipeline(
    user_request: str,
    task_class: TaskClass,
    llm_call_fn,
    existing_response: str,
    context_messages: Optional[List[Dict]] = None,
) -> CritiquePipelineResult:
    """Run Critique→Revise pipeline on the given existing response.

    The generate step is skipped — the artifact to evaluate is
    ``existing_response`` (the LangGraph agent's final answer).

    Args:
        user_request: The original user request.
        task_class: The classified task class (COMPLEX or CREATIVE).
        llm_call_fn: Callable that takes (messages, temperature) and returns a string.
        existing_response: The response from the LangGraph agent to critique/revise.
        context_messages: Optional conversation context (used for rubric framing).

    Returns:
        CritiquePipelineResult with the (possibly revised) response and metadata.
    """
    start_time = time.time()
    stages_fired: List[str] = []

    # ── Step (omitted): Generate ──
    # No generation; we critique the existing LangGraph answer.
    # If a generate is desired, callers should pass the generated text as
    # ``existing_response`` in a future invocation.

    # ── Step 1: Critique ──
    rubric = CRITIQUE_RUBRICS.get(task_class, "")
    if not rubric:
        # No rubric for this class — skip critique, return as-is
        return CritiquePipelineResult(
            response=existing_response,
            was_revised=False,
            critique=None,
            cost_latency_ms=(time.time() - start_time) * 1000,
            stages_fired=stages_fired,
        )

    stages_fired.append("critique")
    critique_prompt = (
        f"{rubric}\n\n"
        f"USER REQUEST: {user_request[:1000]}\n\n"
        f"RESPONSE TO EVALUATE:\n{existing_response[:3000]}\n\n"
        f'Output JSON: {{"issues": ["issue1", ...], "severity": "none|low|medium|high", '
        f'"should_revise": true/false}}\n'
        f"Output ONLY the JSON."
    )

    try:
        critique_response = llm_call_fn(
            messages=[
                {"role": "system", "content": "You are a strict quality reviewer. Output only valid JSON."},
                {"role": "user", "content": critique_prompt},
            ],
            temperature=0.0,
        )
        critique = _parse_critique_response(critique_response)
    except Exception as e:
        logger.warning(f"Critique call failed: {e}")
        critique = CritiqueResult(raw_response=str(e))

    # ── Step 2: Revise (only if needed) ──
    if not critique.should_revise or critique.severity == "none":
        return CritiquePipelineResult(
            response=existing_response,
            was_revised=False,
            critique=critique,
            cost_latency_ms=(time.time() - start_time) * 1000,
            stages_fired=stages_fired,
        )

    stages_fired.append("revise")
    issues_text = "\n".join(f"- {issue}" for issue in critique.issues[:5])
    revision_prompt = (
        f"REVISE your response based on this critique:\n\n"
        f"ISSUES FOUND:\n{issues_text}\n\n"
        f"SEVERITY: {critique.severity}\n\n"
        f"ORIGINAL REQUEST: {user_request[:1000]}\n\n"
        f"YOUR PREVIOUS RESPONSE:\n{existing_response[:3000]}\n\n"
        f"Rewrite the response fixing the issues above. Output ONLY the revised response."
    )

    try:
        revised = llm_call_fn(
            messages=[
                {"role": "system", "content": "You are a revision editor. Fix the issues and output the improved response."},
                {"role": "user", "content": revision_prompt},
            ],
            temperature=0.3,
        )
        if revised and not revised.startswith("Error"):
            return CritiquePipelineResult(
                response=revised,
                was_revised=True,
                critique=critique,
                cost_latency_ms=(time.time() - start_time) * 1000,
                stages_fired=stages_fired,
            )
    except Exception as e:
        logger.warning(f"Revision call failed: {e}")

    # Revision failed — return original
    return CritiquePipelineResult(
        response=existing_response,
        was_revised=False,
        critique=critique,
        cost_latency_ms=(time.time() - start_time) * 1000,
        stages_fired=stages_fired,
    )


# ── Phase 4: Tool-Result Verification ────────────────────

# Hard retry cap for tool verification failures (configurable via env)
import os as _os
_TOOL_VERIFY_MAX_RETRIES = int(_os.getenv("NALLY_HARNESS_VERIFY_RETRIES", "2"))


@dataclass
class ToolVerification:
    """Structured result of tool-call verification."""
    action: str = ""
    result: str = ""
    evidence: str = ""
    satisfies_objective: bool = False
    confidence: float = 0.0
    reasoning: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action": self.action,
            "result": self.result[:200],
            "evidence": self.evidence,
            "satisfies_objective": self.satisfies_objective,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
        }


def verify_tool_result(
    tool_name: str,
    tool_args: Dict[str, Any],
    tool_result: str,
    tool_success: bool,
    objective: str = "",
) -> ToolVerification:
    """Verify a tool call result before the harness treats it as complete.

    Checks:
    (a) Did the tool call return without error?
    (b) Does the result address the stated objective?
    (c) Is there evidence the objective was met, not just attempted?

    Args:
        tool_name: Name of the tool that was called.
        tool_args: Arguments passed to the tool.
        tool_result: The tool's output text.
        tool_success: Whether the tool reported success.
        objective: The task objective from the scratchpad (if available).

    Returns:
        ToolVerification with structured verification result.
    """
    result_lower = tool_result.lower() if tool_result else ""

    # (a) Did the tool return without error?
    error_tokens = (
        "traceback", "error:", "exception:", "permissionerror",
        "filenotfounderror", "modulenotfounderror", "valueerror",
        "typeerror", "keyerror", "indexerror", "runtimeerror",
    )
    has_hard_error = any(token in result_lower for token in error_tokens)

    # Empty result is suspicious
    is_empty = not tool_result or tool_result.strip() in ("", "None", "null", "ok", "done")

    if has_hard_error or (not tool_success):
        return ToolVerification(
            action=f"{tool_name}({json.dumps(tool_args, default=str)[:200]})",
            result=tool_result[:200] if tool_result else "",
            evidence="",
            satisfies_objective=False,
            confidence=0.9,
            reasoning=f"Tool returned error or reported failure",
        )

    if is_empty:
        return ToolVerification(
            action=f"{tool_name}({json.dumps(tool_args, default=str)[:200]})",
            result=tool_result[:200] if tool_result else "",
            evidence="",
            satisfies_objective=False,
            confidence=0.7,
            reasoning="Tool returned empty or trivial result",
        )

    # (b) Does the result address the objective?
    # Simple heuristic: if objective is provided, check for keyword overlap
    satisfies = True
    confidence = 0.6
    evidence_parts = []

    if objective:
        objective_words = set(objective.lower().split())
        # Remove stopwords
        stop = {"the", "a", "an", "and", "or", "but", "in", "on", "at", "to",
                "for", "of", "with", "by", "from", "is", "it", "this", "that"}
        objective_words -= stop

        result_words = set(result_lower.split())
        overlap = objective_words & result_words

        if len(objective_words) > 0:
            match_ratio = len(overlap) / len(objective_words)
            if match_ratio < 0.1:
                satisfies = False
                confidence = 0.4
            elif match_ratio < 0.3:
                confidence = 0.5
            else:
                confidence = min(0.6 + match_ratio * 0.3, 0.9)

    # (c) Is there evidence of completion vs just attempt?
    completion_signals = (
        "successfully", "created", "installed", "deployed", "completed",
        "saved", "written", "updated", "configured", "running",
    )
    has_completion = any(sig in result_lower for sig in completion_signals)
    if has_completion:
        confidence = min(confidence + 0.15, 0.95)
        evidence_parts.append("completion signal detected")

    return ToolVerification(
        action=f"{tool_name}({json.dumps(tool_args, default=str)[:200]})",
        result=tool_result[:200],
        evidence="; ".join(evidence_parts) if evidence_parts else "result present",
        satisfies_objective=satisfies,
        confidence=confidence,
        reasoning="Passed all checks" if satisfies else "Low objective match",
    )
