"""Nally Planner — Simplified LangGraph planning pipeline.

Plan-and-Execute pattern (matching LangGraph's official tutorial):
    classify -> (planner | llm)
    planner -> execute_step -> replan -> (execute_step | planner | synthesize | llm)
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
    PLAN_ENABLED,
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


class Plan:
    __slots__ = ("created_at", "goal", "revision_count", "status", "steps", "summary")

    def __init__(self, goal: str, steps: Optional[List[PlanStep]] = None):
        self.goal = goal
        self.steps = steps or []
        self.status = PlanStatus.ACTIVE
        self.revision_count = 0
        self.created_at = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.summary: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "steps": [s.to_dict() for s in self.steps],
            "status": self.status.value,
            "revision_count": self.revision_count,
            "created_at": self.created_at,
            "summary": self.summary,
        }


# ── Classification ────────────────────────────────────────

_PLAN_SIGNALS = [
    (r"\b(and|then|also|plus)\b.{10,}\b(and|then|also|plus)\b", "multiple_actions"),
    (r"\b(build|create|deploy|migrate|set up|implement|develop|scaffold)\b.{20,}", "creation_task"),
    (r"\b(step by step|break down|plan|roadmap|phases)\b", "explicit_planning"),
    (r"\b(from scratch|entire|full stack|complete)\b", "large_scope"),
    (r"\b(research|analyze|compare|evaluate)\b.{10,}\b(and|then)\b.{10,}", "research_then_act"),
    (r"\b(test|lint|verify|deploy)\b.{10,}\b(and|then)\b.{10,}\b(test|lint|verify|deploy)\b", "multi_stage"),
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

    Requires 2+ plan signals to trigger planning.
    """
    text_lower = text.lower()

    for pattern in _SIMPLE_SIGNALS:
        if re.search(pattern, text_lower):
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
    """Classify whether the user request needs a plan.

    Fast path: regex patterns. Only triggers for genuinely complex requests.
    """
    from langchain_core.messages import HumanMessage

    thread_id = state.get("thread_id", "default")

    # Abort check
    try:
        from ..core.abort import check_abort, clear_abort

        if check_abort(thread_id):
            clear_abort(thread_id)
            return {**state, "plan_status": "none"}
    except Exception:
        pass

    if not PLAN_ENABLED:
        return {**state, "plan_status": "none"}

    # Extract latest user message
    user_text = ""
    messages = state.get("messages", [])
    for msg in reversed(messages):
        if isinstance(msg, HumanMessage):
            user_text = msg.content
            break

    if not user_text:
        return {**state, "plan_status": "none"}

    decision = classify_by_patterns(user_text)

    cl_span = _span("plan_classify", {"text": user_text})
    if cl_span is not None:
        try:
            tracer.end_span(cl_span.span_id, output={"decision": decision})
        except Exception:
            pass

    if decision == "plan":
        logger.info(f"Planning triggered for: {user_text[:80]}")
        return {**state, "plan_status": "planning"}

    return {**state, "plan_status": "none"}


def planner_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Generate or revise a plan for the user's goal.

    Uses timeout-protected LLM call. Falls back to ReAct on failure.
    """
    from langchain_core.messages import HumanMessage

    from ..events.bus import event_bus
    from .llm import llm

    messages = state.get("messages", [])
    thread_id = state.get("thread_id", "default")
    existing_plan = state.get("plan")

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

    if is_revision:
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
            **state,
            "plan": plan,
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


def execute_step_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Execute the next pending step in the plan.

    Single execution path: all steps go through a mini ReAct sub-loop.
    """
    from ..events.bus import event_bus

    plan = state.get("plan")
    if not plan or plan.status != PlanStatus.ACTIVE:
        return state

    thread_id = state.get("thread_id", "default")

    # Abort check
    try:
        from ..core.abort import check_abort, clear_abort

        if check_abort(thread_id):
            clear_abort(thread_id)
            return {**state, "plan_status": "none"}
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

        return {**state, "step_results": step_results}

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

        return state


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
    plan = state.get("plan")
    if not plan:
        return state

    pending = [s for s in plan.steps if s.status == StepStatus.PENDING]
    failed = [s for s in plan.steps if s.status == StepStatus.FAILED]

    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 100)
    iteration += 1

    if iteration >= max_iterations:
        plan.status = PlanStatus.COMPLETE
        return {**state, "iteration": iteration, "plan_status": "complete", "plan": plan}

    # All done — no pending, no failed
    if not pending and not failed:
        plan.status = PlanStatus.COMPLETE
        return {**state, "iteration": iteration, "plan_status": "complete", "plan": plan}

    # Too many revisions — give up
    if plan.revision_count >= PLAN_MAX_REVISIONS:
        plan.status = PlanStatus.COMPLETE
        return {**state, "iteration": iteration, "plan_status": "complete", "plan": plan}

    # Has failures — revise the plan
    if failed:
        plan.status = PlanStatus.REVISING
        return {**state, "iteration": iteration, "plan_status": "revising", "plan": plan}

    # Still has pending steps — keep executing
    return {**state, "iteration": iteration}


def synthesize_node(state: Dict[str, Any]) -> Dict[str, Any]:
    """Combine all step results into a final coherent response."""
    from langchain_core.messages import AIMessage

    from ..events.bus import event_bus
    from .llm import llm

    plan = state.get("plan")
    step_results = state.get("step_results", {})

    if not plan:
        return state

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
            **state,
            "plan": plan,
            "plan_status": "complete",
            "messages": [AIMessage(content=response)],
        }

    except concurrent.futures.TimeoutError:
        logger.warning("Synthesis LLM call timed out, using fallback")
        fallback = _fallback_synthesis(plan, step_results)
        return {
            **state,
            "plan": plan,
            "plan_status": "complete",
            "messages": [AIMessage(content=fallback)],
        }
    except Exception as e:
        logger.error(f"Synthesis failed: {e}")
        fallback = _fallback_synthesis(plan, step_results)
        return {
            **state,
            "plan": plan,
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
    for s in state.get("plan", Plan("")).steps:
        if s.status == StepStatus.COMPLETED and s.id in step_results:
            context_lines.append(f"  [{s.id}] {s.goal}: {step_results[s.id][:300]}")

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

    # Still executing — go back to execute_step
    return "execute_step"
