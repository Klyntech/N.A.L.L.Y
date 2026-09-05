"""Nally Planner — Simplified LangGraph planning pipeline.

Plan-and-Execute pattern (matching LangGraph's official tutorial):
    classify -> (planner | llm)
    planner -> critique -> (execute_step | planner)
    execute_step -> replan -> (execute_step | planner | synthesize | llm)
    synthesize -> END

Flat step list, no dependency DAG. Single execution path via mini ReAct loop.
"""

import concurrent.futures
import json
import re
import time
from enum import StrEnum
from typing import Any, Dict, List, Optional

from ..config import (
    PLAN_MAX_REVISIONS,
    PLAN_MAX_STEPS,
    PLAN_STEP_MAX_ITERATIONS,
    PLAN_STEP_TIMEOUT,
)
from ..core.tracing import tracer
from ..utils.logger import logger

# ── Timeout Helper ────────────────────────────────────────


def _span(name: str, input: dict):
    """Start a traced span as a child of the current span. Never raises on failure."""
    try:
        cur = tracer.get_current_span()
        return tracer.start_span(
            name,
            input,
            parent_span_id=cur.span_id if cur else None,
            run_id=cur.run_id if cur else None,
        )
    except Exception:
        return None


def _call_with_timeout(func, timeout=PLAN_STEP_TIMEOUT):
    """Run a function with a wall-clock timeout. Raises TimeoutError if exceeded.

    The executor is torn down WITHOUT waiting for the abandoned task so a
    slow call cannot block the caller past the timeout (audit Broken #10).
    """
    executor = concurrent.futures.ThreadPoolExecutor(
        max_workers=1, thread_name_prefix="planner-timeout"
    )
    future = executor.submit(func)
    try:
        return future.result(timeout=timeout)
    except concurrent.futures.TimeoutError:
        future.cancel()
        raise
    finally:
        executor.shutdown(wait=False, cancel_futures=True)


# ── Data Structures ───────────────────────────────────────


class StepStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PlanStatus(StrEnum):
    ACTIVE = "active"
    COMPLETE = "complete"
    FAILED = "failed"
    REVISING = "revising"


class PlanStep:
    __slots__ = ("error", "goal", "id", "result", "status")

    def __init__(self, id: str, goal: str):
        self.id = id
        self.goal = goal
        self.status = StepStatus.PENDING
        self.result: Optional[str] = None
        self.error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "goal": self.goal,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "PlanStep":
        step = cls(id=data["id"], goal=data["goal"])
        step.status = StepStatus(data.get("status", "pending"))
        step.result = data.get("result")
        step.error = data.get("error")
        return step


class Plan:
    __slots__ = ("created_at", "critique", "goal", "revision_count", "status", "steps", "summary")

    def __init__(self, goal: str, steps: Optional[List[PlanStep]] = None):
        self.goal = goal
        self.steps = steps or []
        self.status = PlanStatus.ACTIVE
        self.revision_count = 0
        self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.summary: Optional[str] = None
        self.critique: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status.value,
            "revision_count": self.revision_count,
            "created_at": self.created_at,
            "summary": self.summary,
            "critique": self.critique,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Plan":
        plan = cls(
            goal=data["goal"],
            steps=[PlanStep.from_dict(s) for s in data.get("steps", [])],
        )
        plan.status = PlanStatus(data.get("status", "active"))
        plan.revision_count = data.get("revision_count", 0)
        plan.created_at = data.get("created_at", plan.created_at)
        plan.summary = data.get("summary")
        plan.critique = data.get("critique")
        return plan


def _get_plan(state: Dict[str, Any]) -> Optional[Plan]:
    """Extract a Plan object from state, converting from dict if needed.

    The checkpointer (msgpack/SQLite) serializes state values.  We store
    Plan as a plain dict so the checkpointer never sees a live Plan object.
    This helper restores the Plan on every read.
    """
    raw = state.get("plan")
    if raw is None:
        return None
    if isinstance(raw, dict):
        return Plan.from_dict(raw)
    if isinstance(raw, Plan):
        return raw
    logger.warning(f"Unexpected plan type in state: {type(raw).__name__}")
    return None


def _plan_to_state(state: Dict[str, Any], plan: Optional[Plan]) -> Dict[str, Any]:
    """Return a state patch that stores the plan as a dict for checkpointing.

    If *plan* is None the patch sets ``"plan": None``; otherwise the dict
    produced by ``Plan.to_dict()`` is stored so that the msgpack checkpointer
    can serialise it without error.
    """
    return {**state, "plan": plan.to_dict() if plan is not None else None}


# ── Classification ────────────────────────────────────────

_PLAN_SIGNALS = [
    (r"\b(and|then|also|plus)\b.{10,}\b(and|then|also|plus)\b", "multiple_actions"),
    (r"\b(build|create|deploy|migrate|set up|implement|develop|scaffold)\b.{20,}", "creation_task"),
    (r"\b(step by step|break down|plan|roadmap|phases)\b", "explicit_planning"),
    (r"\b(from scratch|entire|full stack|complete)\b", "large_scope"),
    (r"\b(research|analyze|compare|evaluate)\b.{10,}\b(and|then)\b.{10,}", "research_then_act"),
    (r"\b(test|lint|verify|deploy)\b.{10,}\b(and|then)\b.{10,}\b(test|lint|verify|deploy)\b", "multi_stage"),
    # Comma-separated action lists: "build X, deploy Y, configure Z"
    (r"\b(build|create|deploy|migrate|set up|configure|install)\b.{5,}[,;].{5,}\b(build|create|deploy|migrate|set up|configure|install)\b", "comma_actions"),
]

_SIMPLE_SIGNALS = [
    r"^(what|how|why|when|where|who)\s",
    r"^(hey|hi|hello|thanks|ok|yes|no|lol|haha)\b",
    r"^(remember|recall|forget)\b",
    r"^(who (am i|are you)|what('s| is) your)",
    r"^(explain|tell me about|define)\b",
]


def classify_by_patterns(text: str) -> str:
    """Fast regex classification. Returns 'plan' or 'simple'.

    Cost guard: short queries (<50 words) without action keywords are always
    classified as 'simple' to avoid wasting LLM calls on trivial multi-clause
    queries like "weather and time in Lagos".
    """
    text_lower = text.lower()

    for pattern in _SIMPLE_SIGNALS:
        if re.search(pattern, text_lower):
            return "simple"

    # Cost guard: short queries without action keywords → force simple.
    # Also allow through if3+ sentences (multi-clause regardless of keywords).
    word_count = len(text.split())
    _ACTION_KEYWORDS = ("build", "create", "deploy", "migrate", "set up", "setup", "configure", "install")
    sentence_count_check = text.count(".") + text.count("!") + text.count("?")
    has_action = any(kw in text_lower for kw in _ACTION_KEYWORDS)
    if word_count < 50 and not has_action and sentence_count_check < 3:
        return "simple"

    plan_score = 0
    for pattern, _label in _PLAN_SIGNALS:
        if re.search(pattern, text_lower):
            plan_score += 1

    sentence_count = text.count(".") + text.count("!") + text.count("?")
    if sentence_count >= 3:
        plan_score += 1

    if plan_score >= 2:
        return "plan"
    return "simple"


# ── Plan Prompt ───────────────────────────────────────────

PLANNER_SYSTEM_PROMPT = """You are a task planner. For the given objective, come up with a simple
step-by-step plan. This plan should involve individual tasks, that if
executed correctly will yield the correct answer. Do not add any
superfluous steps. The result of the final step should be the final
answer. Make sure that each step has all the information needed — do
not skip steps.

OUTPUT FORMAT: A JSON object with this exact structure:
{
  "goal": "original user goal",
  "steps": [
    {"id": "step_1", "goal": "what this step accomplishes"},
    {"id": "step_2", "goal": "what this step accomplishes"}
  ]
}

RULES:
- Steps must be in logical execution order
- Max 10 steps
- Each step should be atomic and testable
- Output ONLY the JSON object. No explanation, no markdown."""


CRITIQUE_SYSTEM_PROMPT = """You are reviewing a plan before it executes. You will be given
the user's original goal and a proposed step list. Judge only whether the steps, as a set,
are necessary and sufficient to achieve the goal — not how they will be implemented.

Output ONLY a JSON object, no markdown, no explanation outside the JSON:
{"verdict": "approve"}
or
{"verdict": "revise", "reason": "<one or two sentences: what's missing, redundant, or wrong>"}

Approve unless there is a clear, specific defect (missing necessary step, redundant step,
step that doesn't serve the stated goal, wrong order/dependency). Do not revise for style."""


# ── Parsing ───────────────────────────────────────────────


def parse_plan_response(response: str, fallback_goal: str) -> Optional[Plan]:
    """Parse LLM response as a Plan object."""
    try:
        start = response.find("{")
        end = response.rfind("}")
        if start == -1 or end == -1:
            return None

        json_str = response[start : end + 1]
        data = json.loads(json_str)

        if "steps" not in data or not isinstance(data["steps"], list):
            return None

        steps = []
        for i, s in enumerate(data["steps"]):
            step = PlanStep(
                id=s.get("id", f"step_{i + 1}"),
                goal=s.get("goal", ""),
            )
            steps.append(step)

        plan = Plan(goal=data.get("goal", fallback_goal), steps=steps)
        return plan

    except (json.JSONDecodeError, ValueError, KeyError) as e:
        logger.warning(f"Plan parse failed: {e}")
        return None


# ── Validation ────────────────────────────────────────────


def validate_plan(plan: Plan) -> Plan:
    """Validate plan structure and enforce limits."""
    if len(plan.steps) > PLAN_MAX_STEPS:
        plan.steps = plan.steps[:PLAN_MAX_STEPS]
        logger.warning(f"Plan truncated to {PLAN_MAX_STEPS} steps")
    return plan


# ── Graph Nodes ───────────────────────────────────────────


def classify_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Decide execution strategy via TaskRouter (automatic planning).

    Preferred path: consume the authoritative RouteDecision supplied by core
    via run_agent (no second routing). Falls back to a single TaskRouter
    call only when no decision was supplied (legacy/tests/plan-step loops).
    PLAN_ENABLED is only an operational kill-switch — ordinary tasks
    do not require a user-facing plan toggle.
    """
    from langchain_core.messages import HumanMessage

    from .task_router import RouteDecision, Strategy, route, strategy_to_plan_status

    thread_id = state.get("thread_id", "default")

    try:
        from ..core.abort import check_abort, clear_abort

        if check_abort(thread_id):
            clear_abort(thread_id)
            return {**state, "plan_status": "none", "strategy": Strategy.REACT.value}
    except Exception:
        pass

    # Authoritative path: core already decided. Consume it verbatim.
    supplied = state.get("route_decision")
    if isinstance(supplied, dict) and supplied.get("strategy"):
        try:
            strat_raw = supplied.get("strategy")
            strat = Strategy(strat_raw.value if hasattr(strat_raw, "value") else str(strat_raw))
        except Exception:
            strat = Strategy.REACT
        decision = RouteDecision(
            strategy=strat,
            task_class=str(supplied.get("task_class") or ""),
            confidence=float(supplied.get("confidence") or 0.0),
            reasoning=str(supplied.get("reasoning") or "authoritative route from core"),
            method=str(supplied.get("method") or "core"),
            pipeline=supplied.get("pipeline"),
        )
        plan_status = strategy_to_plan_status(decision)
        logger.debug(f"classify_node: consuming authoritative strategy={decision.strategy.value} (no re-route)")
        return {
            **state,
            "plan_status": plan_status,
            "strategy": decision.strategy.value,
            "route_decision": decision.to_dict(),
        }

    user_text = ""
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            user_text = msg.content
            break

    if not user_text:
        return {**state, "plan_status": "none", "strategy": Strategy.REACT.value}

    # Reconstruct a minimal classification from state if core/harness attached one
    classification = None
    intent = state.get("intent_class") or state.get("task_class")
    if intent:
        class _Cls:
            pass

        classification = _Cls()
        classification.task_class = intent
        classification.confidence = float(state.get("intent_confidence") or 0.0)
        classification.reasoning = state.get("intent_reasoning") or ""
        classification.method = "harness"

    decision = route(user_text, classification=classification)
    # Single decision point: TaskRouter owns promotion + PLAN_ENABLED kill-switch.
    # The legacy classify_by_patterns() override was removed here to prevent a
    # second classifier silently overriding the authoritative decision.

    plan_status = strategy_to_plan_status(decision)

    cl_span = _span(
        "plan_classify",
        {
            "text": user_text[:200],
            "strategy": decision.strategy.value,
            "task_class": decision.task_class,
            "method": decision.method,
        },
    )
    if cl_span is not None:
        try:
            tracer.end_span(
                cl_span.span_id,
                output={"strategy": decision.strategy.value, "plan_status": plan_status},
            )
        except Exception:
            pass

    if plan_status == "planning":
        logger.info(f"TaskRouter → PLAN ({decision.task_class or decision.method}) for: {user_text[:80]}")
    else:
        logger.debug(f"TaskRouter → {decision.strategy.value} for: {user_text[:80]}")

    return {
        **state,
        "plan_status": plan_status,
        "strategy": decision.strategy.value,
        "route_decision": decision.to_dict(),
    }



def planner_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Generate or revise a plan for the user's goal.

    Uses timeout-protected LLM call. Falls back to ReAct on failure.
    """
    from langchain_core.messages import HumanMessage

    from ..events.bus import event_bus
    from .llm import llm

    messages = state.get("messages", [])
    thread_id = state.get("thread_id", "default")
    existing_plan = _get_plan(state)

    # Abort check
    try:
        from ..core.abort import check_abort, clear_abort

        if check_abort(thread_id):
            clear_abort(thread_id)
            return {**state, "plan_status": "none", "plan": None}
    except Exception:
        pass

    # Extract user goal
    user_text = ""
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            user_text = msg.content
            break

    if not user_text:
        return {**state, "plan_status": "none", "plan": None}

    # Build planning prompt
    is_revision = existing_plan and existing_plan.status == PlanStatus.REVISING

    # Goal deduplication: if an active plan already exists for the same goal,
    # don't re-plan. This prevents the infinite planner->critique->replan loop
    # when steps keep failing for the same reason.
    if existing_plan and not is_revision and existing_plan.status == PlanStatus.ACTIVE:
        if existing_plan.goal == user_text or (
            existing_plan.goal and user_text in existing_plan.goal
        ):
            logger.info("Planner dedup: existing plan covers goal, skipping re-plan")
            return {**_plan_to_state(state, existing_plan), "plan_status": "executing"}

    if is_revision and existing_plan.critique:
        prompt = (
            f"The plan for '{user_text}' was reviewed and needs revision:\n"
            f"{existing_plan.critique}\n\n"
            f"Previous plan steps:\n"
            + "\n".join(f"  {s.id}: {s.goal}" for s in existing_plan.steps)
            + "\n\nRevise the plan to address this feedback."
        )
        existing_plan.critique = None
    elif is_revision:
        failed_steps = [s for s in existing_plan.steps if s.status == StepStatus.FAILED]
        failure_context = "\n".join(f"  Step '{s.id}' ({s.goal}) failed: {s.error}" for s in failed_steps)
        prompt = (
            f"The previous plan for '{user_text}' had failures:\n{failure_context}\n\n"
            f"Previous plan steps:\n"
            + "\n".join(f"  {s.id}: {s.goal} [{s.status.value}]" for s in existing_plan.steps)
            + "\n\nRevise the plan to work around these failures. "
            "Keep successful steps, replace or modify failed ones."
        )
    else:
        prompt = f"Create a plan for: {user_text}"

    try:
        span = _span("plan_generate", {"prompt": prompt, "is_revision": is_revision})
        response = _call_with_timeout(
            lambda: llm.simple_chat(
                user_message=prompt,
                system_prompt=PLANNER_SYSTEM_PROMPT,
            ),
            timeout=60,
        )
        plan = parse_plan_response(response, user_text)

        if span is not None:
            try:
                tracer.end_span(
                    span.span_id,
                    output={
                        "response": response,
                        "plan_ok": plan is not None,
                        "step_count": len(plan.steps) if plan is not None else 0,
                    },
                )
            except Exception:
                pass

        if plan is None:
            logger.warning("Plan generation returned invalid JSON, falling back to ReAct")
            return {**state, "plan_status": "none", "plan": None}

        plan = validate_plan(plan)

        if is_revision:
            plan.revision_count = existing_plan.revision_count + 1

        event_bus.publish(
            "plan_created",
            {
                "goal": plan.goal,
                "step_count": len(plan.steps),
                "steps": [{"id": s.id, "goal": s.goal} for s in plan.steps],
            },
        )

        return {
            **_plan_to_state(state, plan),
            "plan_status": "executing",
            "current_step_index": 0,
            "step_results": state.get("step_results", {}),
        }

    except concurrent.futures.TimeoutError:
        logger.warning("Planner LLM call timed out (60s), falling back to ReAct")
        return {**state, "plan_status": "none", "plan": None}
    except Exception as e:
        logger.error(f"Plan generation failed: {e}")
        return {**state, "plan_status": "none", "plan": None}


def critique_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Review a freshly generated plan against the user's goal before execution.

    Fails open: any error, timeout, or unparseable response approves the plan rather
    than blocking execution. Bounded by PLAN_MAX_REVISIONS (shared with replan's
    failure-repair revisions via plan.revision_count).
    """
    from .llm import llm

    plan = _get_plan(state)
    if not plan:
        return {**state, "plan_status": "complete"}

    if plan.revision_count >= PLAN_MAX_REVISIONS:
        logger.warning("Critique skipped: revision limit reached, approving plan as-is")
        return {**_plan_to_state(state, plan), "plan_status": "executing"}

    span = _span("plan_critique", {"goal": plan.goal, "step_count": len(plan.steps)})
    try:
        prompt = (
            f"User's goal: {plan.goal}\n\nProposed steps:\n"
            + "\n".join(f"  {s.id}: {s.goal}" for s in plan.steps)
        )
        response = _call_with_timeout(
            lambda: llm.simple_chat(user_message=prompt, system_prompt=CRITIQUE_SYSTEM_PROMPT),
            timeout=30,
        )
        verdict = json.loads(response.strip())

        if span is not None:
            try:
                tracer.end_span(span.span_id, output={"verdict": verdict.get("verdict")})
            except Exception:
                pass

        if verdict.get("verdict") == "revise" and verdict.get("reason"):
            plan.status = PlanStatus.REVISING
            plan.critique = verdict["reason"]
            return {**_plan_to_state(state, plan), "plan_status": "critique_revising"}

        return {**_plan_to_state(state, plan), "plan_status": "executing"}

    except Exception as e:
        logger.warning(f"Plan critique failed ({e}), approving plan as-is")
        if span is not None:
            try:
                tracer.end_span(span.span_id, error=str(e))
            except Exception:
                pass
        return {**state, "plan_status": "executing"}


def route_after_critique(state: Dict[str, Any]) -> str:
    """Route after plan critique: revise or proceed to execution."""
    if state.get("plan_status") == "critique_revising":
        return "planner"
    return "execute_step"


def execute_step_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Execute the next pending step in the plan.

    Single execution path: all steps go through a mini ReAct sub-loop.
    """
    from ..events.bus import event_bus

    plan = _get_plan(state)
    if not plan or plan.status != PlanStatus.ACTIVE:
        return state

    thread_id = state.get("thread_id", "default")

    # Abort check
    try:
        from ..core.abort import check_abort, clear_abort

        if check_abort(thread_id):
            clear_abort(thread_id)
            return {**_plan_to_state(state, plan), "plan_status": "none"}
    except Exception:
        pass

    # Find first pending step
    step = None
    for i, s in enumerate(plan.steps):
        if s.status == StepStatus.PENDING:
            step = s
            state["current_step_index"] = i
            break

    if not step:
        return state

    step.status = StepStatus.RUNNING

    event_bus.publish(
        "plan_step_started",
        {
            "step_id": step.id,
            "goal": step.goal,
        },
    )

    try:
        result = _execute_step(step, state)

        step.status = StepStatus.COMPLETED
        step.result = result
        step_results = dict(state.get("step_results", {}))
        step_results[step.id] = result

        event_bus.publish(
            "plan_step_completed",
            {
                "step_id": step.id,
                "success": True,
            },
        )

        return {**_plan_to_state(state, plan), "step_results": step_results}

    except Exception as e:
        step.status = StepStatus.FAILED
        step.error = str(e)
        logger.error(f"Step {step.id} failed: {e}")

        event_bus.publish(
            "plan_step_completed",
            {
                "step_id": step.id,
                "success": False,
                "error": str(e),
            },
        )

        return {**_plan_to_state(state, plan)}


def replan_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Check plan progress and decide: continue, revise, or synthesize.

    Matches LangGraph's replan pattern: checks if we're done, if revisions
    are needed, or if more steps remain.
    """
    replan_span = _span("plan_replan", {"plan_status": state.get("plan_status"), "step_results": state.get("step_results")})
    out = _replan_decision(state)
    if replan_span is not None:
        try:
            tracer.end_span(replan_span.span_id, output={"plan_status": out.get("plan_status")})
        except Exception:
            pass
    return out


def _replan_decision(state: Dict[str, Any]) -> Dict[str, Any]:
    plan = _get_plan(state)
    if not plan:
        return state

    pending = [s for s in plan.steps if s.status == StepStatus.PENDING]
    failed = [s for s in plan.steps if s.status == StepStatus.FAILED]

    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 100)
    iteration += 1

    if iteration >= max_iterations:
        plan.status = PlanStatus.COMPLETE
        return {**_plan_to_state(state, plan), "iteration": iteration, "plan_status": "complete"}

    # All done — no pending, no failed
    if not pending and not failed:
        plan.status = PlanStatus.COMPLETE
        return {**_plan_to_state(state, plan), "iteration": iteration, "plan_status": "complete"}

    # Too many revisions — give up
    if plan.revision_count >= PLAN_MAX_REVISIONS:
        plan.status = PlanStatus.COMPLETE
        return {**_plan_to_state(state, plan), "iteration": iteration, "plan_status": "complete"}

    # Has failures — revise the plan
    if failed:
        plan.status = PlanStatus.REVISING
        return {**_plan_to_state(state, plan), "iteration": iteration, "plan_status": "revising"}

    # Still has pending steps — keep executing
    return {**_plan_to_state(state, plan), "iteration": iteration}


def synthesize_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Combine all step results into a final coherent response."""
    from langchain_core.messages import AIMessage

    from ..events.bus import event_bus
    from .llm import llm

    plan = _get_plan(state)
    step_results = state.get("step_results", {})

    if not plan:
        return {
            **state,
            "messages": state.get("messages", []) + [
                AIMessage(content="I tried to plan that out but couldn't put a plan together. Let me try directly.")
            ],
        }

    # Build synthesis prompt
    step_summaries = []
    for s in plan.steps:
        status_icon = {"completed": "OK", "failed": "FAIL"}.get(s.status.value, "?")
        result = step_results.get(s.id, s.result or "no result")
        step_summaries.append(f"[{status_icon}] {s.goal}\n  Result: {result[:500] if result else 'none'}")

    synthesis_prompt = (
        f"The user asked: {plan.goal}\n\n"
        f"Here are the results from each execution step:\n\n"
        + "\n".join(step_summaries)
        + "\n\nSynthesize these results into a clear, complete response for the user. "
        "Be specific about what was accomplished and what failed (if any). "
        "Use Nally's casual, direct tone. Start with a capital letter."
    )

    try:
        synth_span = _span("plan_synthesize", {"prompt": synthesis_prompt})
        response = _call_with_timeout(
            lambda: llm.simple_chat(
                user_message=synthesis_prompt,
                system_prompt="You are Nally synthesizing plan results. Be thorough and specific.",
            ),
            timeout=60,
        )
        if synth_span is not None:
            try:
                tracer.end_span(synth_span.span_id, output={"response": response})
            except Exception:
                pass

        plan.summary = response
        plan.status = PlanStatus.COMPLETE

        event_bus.publish(
            "plan_complete",
            {
                "goal": plan.goal,
                "steps_completed": sum(1 for s in plan.steps if s.status == StepStatus.COMPLETED),
                "steps_total": len(plan.steps),
            },
        )

        return {
            **_plan_to_state(state, plan),
            "plan_status": "complete",
            "messages": [AIMessage(content=response)],
        }

    except concurrent.futures.TimeoutError:
        logger.warning("Synthesis LLM call timed out, using fallback")
        fallback = _fallback_synthesis(plan, step_results)
        return {
            **_plan_to_state(state, plan),
            "plan_status": "complete",
            "messages": [AIMessage(content=fallback)],
        }
    except Exception as e:
        logger.error(f"Synthesis failed: {e}")
        fallback = _fallback_synthesis(plan, step_results)
        return {
            **_plan_to_state(state, plan),
            "plan_status": "complete",
            "messages": [AIMessage(content=fallback)],
        }


# ── Execution Strategy ────────────────────────────────────


def _execute_step(step: PlanStep, state: Dict[str, Any]) -> str:
    """Execute a single plan step via a mini ReAct sub-loop."""
    from ..tools.filter import tool_filter
    from ..tools.registry import registry
    from .graph import run_agent

    try:
        tools = tool_filter.select(step.goal)
    except Exception:
        tools = [t.to_openai_schema() for t in registry.tools.values()]

    # Build context from previous step results
    context_lines = []
    step_results = state.get("step_results", {})
    parent_plan = _get_plan(state) or Plan("")
    for s in parent_plan.steps:
        if s.status == StepStatus.COMPLETED and s.id in step_results:
            context_lines.append(f"  [{s.id}] {s.goal}: {(step_results[s.id] or '')[:300]}")

    context = "\n".join(context_lines)
    full_prompt = step.goal
    if context:
        full_prompt = f"Previous step results:\n{context}\n\nCurrent task: {step.goal}"

    messages = [
        {
            "role": "system",
            "content": (
                f"You are executing a single plan step. Complete this task and return the result.\nGoal: {step.goal}"
            ),
        },
        {"role": "user", "content": full_prompt},
    ]

    step_span = None
    try:
        cur = tracer.get_current_span()
        step_span = tracer.start_span(
            "plan_step",
            {"step_id": step.id, "goal": step.goal},
            parent_span_id=cur.span_id if cur else None,
            run_id=cur.run_id if cur else None,
        )
    except Exception:
        step_span = None
    parent_id = step_span.span_id if step_span else None
    parent_run = step_span.run_id if step_span else None

    try:
        result = run_agent(
            messages=messages,
            tools=tools,
            max_iterations=PLAN_STEP_MAX_ITERATIONS,
            thread_id=f"plan-{state.get('thread_id', 'default')}-{step.id}",
            _parent_span_id=parent_id,
            _run_id=parent_run,
        )
        if step_span is not None:
            try:
                tracer.end_span(step_span.span_id, output={"result": result})
            except Exception:
                pass
        return result
    except Exception as e:
        if step_span is not None:
            try:
                tracer.end_span_exc(step_span.span_id, e)
            except Exception:
                pass
        raise


def _fallback_synthesis(plan: Plan, step_results: Dict[str, str]) -> str:
    """Raw synthesis without LLM as fallback."""
    lines = [f"Here's what I did for: {plan.goal}\n"]
    for s in plan.steps:
        icon = {"completed": "+", "failed": "-"}.get(s.status.value, "?")
        result = step_results.get(s.id, s.result or "")
        lines.append(f"[{icon}] {s.goal}")
        if result:
            lines.append(f"  {result[:200]}")
    return "\n".join(lines)


# ── Routing Functions ─────────────────────────────────────


def route_after_classify(state: Dict[str, Any]) -> str:
    """Route after classification: plan or ReAct."""
    if state.get("plan_status") == "planning":
        return "planner"
    return "llm"


def route_after_replan(state: Dict[str, Any]) -> str:
    """Route after replan check."""
    plan_status = state.get("plan_status", "none")

    if plan_status == "complete":
        return "synthesize"

    if plan_status == "revising":
        return "planner"

    # No plan / plan was None — exit to synthesize (error message)
    if plan_status in ("none", None) or not state.get("plan"):
        return "synthesize"

    # Still executing — go back to execute_step
    return "execute_step"
