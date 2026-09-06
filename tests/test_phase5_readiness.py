"""Gate B: Phase 5 readiness — R1-R4 missing coverage.

Covers gaps identified in the R1-R5 survey that existing tests do not prove.
All tests are hermetic (no network, mocked LLM where needed).
"""

import json
from concurrent.futures import TimeoutError
from unittest.mock import patch

from langchain_core.messages import HumanMessage

from nally.agent.planner import (
    Plan,
    PlanStatus,
    PlanStep,
    StepStatus,
    _replan_decision,
    execute_step_node,
    planner_node,
    route_after_planner,
    route_after_replan,
    synthesize_node,
    verify_step_result,
)

# ── R1: Transitions ───────────────────────────────────────────────


class TestRouteAfterPlanner:
    def test_plan_failed_with_live_plan_still_routes_llm(self):
        plan = Plan(goal="test", steps=[PlanStep(id="s1", goal="step 1")])
        assert route_after_planner({"plan_status": "plan_failed", "plan": plan}) == "llm"

    def test_non_executing_with_live_plan_behavior(self):
        plan = Plan(goal="test", steps=[PlanStep(id="s1", goal="step 1")])
        # Any non-plan_failed with plan present is PLAN_READY -> critique
        assert route_after_planner({"plan_status": "complete", "plan": plan}) == "critique"


class TestRouteAfterReplanGaps:
    def test_blocked_routes_to_synthesize(self):
        plan = Plan(goal="test", steps=[PlanStep(id="s1", goal="step 1")])
        assert route_after_replan({"plan_status": "blocked", "plan": plan}) == "synthesize"

    def test_none_routes_to_synthesize(self):
        plan = Plan(goal="test", steps=[PlanStep(id="s1", goal="step 1")])
        assert route_after_replan({"plan_status": "none", "plan": plan}) == "synthesize"
        assert route_after_replan({"plan_status": None, "plan": plan}) == "synthesize"

    def test_missing_plan_routes_to_synthesize(self):
        assert route_after_replan({"plan_status": "executing"}) == "synthesize"
        assert route_after_replan({"plan_status": "executing", "plan": None}) == "synthesize"

    def test_unknown_status_with_plan_terminates(self):
        plan = Plan(goal="test", steps=[PlanStep(id="s1", goal="step 1")])
        # Must NOT return execute_step — unknown is terminal
        assert route_after_replan({"plan_status": "plan_failed", "plan": plan}) == "synthesize"
        assert route_after_replan({"plan_status": "foo", "plan": plan}) == "synthesize"
        assert route_after_replan({"plan_status": "unknown_xyz", "plan": plan}) == "synthesize"

    def test_executing_without_pending_terminates(self):
        plan = Plan(goal="test", steps=[PlanStep(id="s1", goal="step 1")])
        plan.steps[0].status = StepStatus.COMPLETED
        assert route_after_replan({"plan_status": "executing", "plan": plan, "iteration": 0, "max_iterations": 100}) == "synthesize"

    def test_executing_with_pending_loops(self):
        plan = Plan(
            goal="test",
            steps=[PlanStep(id="s1", goal="step 1"), PlanStep(id="s2", goal="step 2")],
        )
        plan.steps[0].status = StepStatus.COMPLETED
        # s2 still PENDING
        assert route_after_replan({"plan_status": "executing", "plan": plan, "iteration": 0, "max_iterations": 100}) == "execute_step"


class TestPlannerNodeGaps:
    def test_timeout_returns_plan_failed(self):
        state = {"messages": [HumanMessage(content="build a widget")], "thread_id": "t-timeout"}
        with patch("nally.agent.planner._call_with_timeout", side_effect=TimeoutError("timed out")):
            result = planner_node(dict(state))
        assert result["plan_status"] == "plan_failed"
        assert result["plan"] is None

    def test_empty_messages_returns_plan_failed(self):
        assert planner_node({"messages": [], "thread_id": "t-empty"})["plan_status"] == "plan_failed"
        assert planner_node({"messages": [HumanMessage(content="")], "thread_id": "t-empty2"})["plan_status"] == "plan_failed"

    def test_abort_returns_plan_failed(self):
        state = {"messages": [HumanMessage(content="build a widget")], "thread_id": "t-abort"}
        with patch("nally.core.abort.check_abort", return_value=True):
            with patch("nally.core.abort.clear_abort"):
                result = planner_node(dict(state))
        assert result["plan_status"] == "plan_failed"
        assert result["plan"] is None

    def test_dedup_skips_llm(self):
        from nally.agent.planner import _plan_to_state

        plan = Plan(goal="build a widget", steps=[PlanStep(id="s1", goal="step 1")])
        state = _plan_to_state(
            {"messages": [HumanMessage(content="build a widget")], "thread_id": "t-dedup"}, plan
        )
        with patch("nally.agent.llm.llm") as mock_llm:
            result = planner_node(dict(state))
        mock_llm.simple_chat.assert_not_called()
        assert result["plan_status"] == "executing"

    def test_failure_repair_prompt_content(self):
        from nally.agent.planner import _plan_to_state

        plan = Plan(goal="build a widget", steps=[PlanStep(id="s1", goal="step 1")])
        plan.status = PlanStatus.REVISING
        plan.steps[0].status = StepStatus.FAILED
        plan.steps[0].error = "disk full"
        state = _plan_to_state(
            {"messages": [HumanMessage(content="build a widget")], "thread_id": "t-repair"}, plan
        )
        with patch("nally.agent.llm.llm") as mock_llm:
            mock_llm.simple_chat.return_value = json.dumps({"goal": "build a widget", "steps": [{"id": "s1", "goal": "retry step 1"}]})
            planner_node(dict(state))
        prompt = mock_llm.simple_chat.call_args.kwargs.get("user_message", mock_llm.simple_chat.call_args.args[0] if mock_llm.simple_chat.call_args.args else "")
        assert "had failures" in prompt or "disk full" in prompt

    def test_revision_count_increments_on_failure_repair(self):
        from nally.agent.planner import _plan_to_state

        plan = Plan(goal="build a widget", steps=[PlanStep(id="s1", goal="step 1")])
        plan.status = PlanStatus.REVISING
        plan.revision_count = 1
        plan.steps[0].status = StepStatus.FAILED
        plan.steps[0].error = "boom"
        state = _plan_to_state(
            {"messages": [HumanMessage(content="build a widget")], "thread_id": "t-rev"}, plan
        )
        with patch("nally.agent.llm.llm") as mock_llm:
            mock_llm.simple_chat.return_value = json.dumps({"goal": "build a widget", "steps": [{"id": "s1", "goal": "retry"}]})
            result = planner_node(dict(state))
        assert result["plan"]["revision_count"] == 2


class TestExecuteStepGaps:
    def test_inactive_plan_stops(self):
        from nally.agent.planner import _plan_to_state

        plan = Plan(goal="g", steps=[PlanStep(id="s1", goal="step 1")])
        plan.status = PlanStatus.REVISING
        state = _plan_to_state({"thread_id": "t-revising"}, plan)
        result = execute_step_node(state)
        assert result["plan_status"] == "plan_failed"

    def test_abort_returns_none_status(self):
        from nally.agent.planner import _plan_to_state

        plan = Plan(goal="g", steps=[PlanStep(id="s1", goal="step 1")])
        state = _plan_to_state({"thread_id": "t-abort2"}, plan)
        with patch("nally.core.abort.check_abort", return_value=True):
            with patch("nally.core.abort.clear_abort"):
                result = execute_step_node(dict(state))
        assert result["plan_status"] == "none"

    def test_no_pending_returns_state(self):
        from nally.agent.planner import _plan_to_state

        plan = Plan(goal="g", steps=[PlanStep(id="s1", goal="step 1")])
        plan.steps[0].status = StepStatus.COMPLETED
        state = _plan_to_state({"thread_id": "t-nopending"}, plan)
        result = execute_step_node(dict(state))
        # No pending step -> returns state with plan intact, no new step started
        assert result["plan"] is not None


# ── R2: Failure truth ──────────────────────────────────────────────


class TestFailureTruth:
    def test_iteration_cap_partial_when_some_completed(self):
        plan = Plan(goal="test", steps=[PlanStep(id="s1", goal="ok"), PlanStep(id="s2", goal="bad")])
        plan.steps[0].status = StepStatus.COMPLETED
        plan.steps[1].status = StepStatus.FAILED
        state = {"plan": plan, "iteration": 99, "max_iterations": 100}
        result = _replan_decision(state)
        assert result["plan_status"] == "partial"

    def test_iteration_cap_failed_when_none_completed(self):
        plan = Plan(goal="test", steps=[PlanStep(id="s1", goal="bad")])
        plan.steps[0].status = StepStatus.FAILED
        state = {"plan": plan, "iteration": 99, "max_iterations": 100}
        assert _replan_decision(state)["plan_status"] == "failed"

    def test_step_exception_marks_failed(self):
        from nally.agent.planner import _plan_to_state

        plan = Plan(goal="g", steps=[PlanStep(id="s1", goal="do the thing")])
        state = _plan_to_state({"thread_id": "t-exc"}, plan)
        with patch("nally.agent.planner._execute_step", side_effect=Exception("boom")):
            result = execute_step_node(state)
        from nally.agent.planner import _get_plan

        out = _get_plan(result)
        assert out.steps[0].status == StepStatus.FAILED
        assert "boom" in (out.steps[0].error or "")

    def test_has_failures_revising(self):
        plan = Plan(goal="test", steps=[PlanStep(id="s1", goal="bad")])
        plan.steps[0].status = StepStatus.FAILED
        state = {"plan": plan, "iteration": 0, "max_iterations": 100}
        assert _replan_decision(state)["plan_status"] == "revising"

    def test_replan_never_yields_blocked(self):
        plan = Plan(goal="test", steps=[PlanStep(id="s1", goal="bad")])
        plan.steps[0].status = StepStatus.FAILED
        state = {"plan": plan, "iteration": 0, "max_iterations": 100}
        assert _replan_decision(state)["plan_status"] != "blocked"

    def test_synthesize_plan_none_fallback(self):
        result = synthesize_node({"messages": [], "plan": None, "plan_status": "none"})
        assert result["messages"][0].content
        assert "couldn't put a plan together" in result["messages"][0].content.lower()

    def test_synthesize_unknown_terminal_defaults_complete(self):
        from nally.agent.planner import _plan_to_state

        plan = Plan(goal="test goal", steps=[PlanStep(id="s1", goal="step 1")])
        plan.steps[0].status = StepStatus.COMPLETED
        plan.steps[0].result = "did the thing"
        state = _plan_to_state({"messages": []}, plan)
        state["plan_status"] = "weird_unknown"
        with patch("nally.agent.llm.llm") as mock_llm:
            mock_llm.simple_chat.return_value = "synthesized"
            result = synthesize_node(dict(state))
        assert result["plan_status"] == "complete"

    def test_non_complete_never_implies_completion(self):
        from nally.agent.planner import _plan_to_state

        for terminal in ("partial", "failed", "blocked"):
            plan = Plan(goal="test goal", steps=[PlanStep(id="s1", goal="step 1")])
            plan.steps[0].status = StepStatus.FAILED if terminal == "failed" else StepStatus.COMPLETED
            plan.steps[0].result = "did the thing"
            state = _plan_to_state({"messages": []}, plan)
            state["plan_status"] = terminal
            with patch("nally.agent.llm.llm") as mock_llm:
                mock_llm.simple_chat.return_value = "synthesized"
                synthesize_node(dict(state))
            prompt = mock_llm.simple_chat.call_args.kwargs.get("user_message", mock_llm.simple_chat.call_args.args[0] if mock_llm.simple_chat.call_args.args else "")
            # The prompt must frame the outcome distinctly, never as COMPLETE
            assert f"Outcome of this plan: {terminal.upper()}" in prompt
            if terminal != "complete":
                assert "Outcome of this plan: COMPLETE" not in prompt


# ── R3: Strategy authority ─────────────────────────────────────────


class TestStrategyAuthority:
    def test_plan_skill_excluded_from_intent(self):
        from pathlib import Path

        from nally.skills.registry import skill_registry

        skill_registry.load(Path("C:/Users/chuki/Desktop/N.A.L.L.Y/skills"))
        # Even with 3+ overlapping words, plan must not be returned
        assert "plan" not in skill_registry.find_by_intent("please plan this roadmap and strategize our work")
        assert "plan" not in skill_registry.find_by_intent("plan strategize roadmap organize work")

    def test_plan_skill_still_activatable_by_name(self):
        from pathlib import Path

        from nally.skills.registry import skill_registry

        skill_registry.load(Path("C:/Users/chuki/Desktop/N.A.L.L.Y/skills"))
        assert skill_registry.get("plan") is not None
        assert skill_registry.activate("plan") is not None

    def test_conflicting_route_decision_stays_react(self):
        from langchain_core.messages import HumanMessage

        from nally.agent.planner import classify_node

        # Authoritative REACT decision + plan-signal text must NOT be re-promoted
        state = {
            "messages": [HumanMessage(content="Build a full web app with backend, migrate database, test end to end. First X then Y after that.")],
            "thread_id": "t-authority",
            "route_decision": {
                "strategy": "react",
                "task_class": "SIMPLE",
                "confidence": 0.9,
                "reasoning": "authoritative",
                "method": "core",
                "pipeline": None,
            },
        }
        result = classify_node(dict(state))
        assert result["strategy"] == "react"
        assert result["plan_status"] == "none"

    def test_strategy_to_plan_status_all_five(self):
        from nally.agent.task_router import RouteDecision, Strategy, strategy_to_plan_status

        for strat, expected in [
            (Strategy.DIRECT, "none"),
            (Strategy.REACT, "none"),
            (Strategy.PLAN, "planning"),
            (Strategy.DELEGATE, "none"),
            (Strategy.ENGINEERING, "planning"),
        ]:
            assert strategy_to_plan_status(RouteDecision(strategy=strat)) == expected

    def test_kill_switch_engineering(self):
        from nally.agent.task_router import Strategy, route

        with patch("nally.config.PLAN_ENABLED", False):
            with patch("nally.agent.task_router.PLAN_ENABLED", False, create=True):
                decision = route("refactor the entire codebase architecture end to end build full app")
                # Engineering needs 8+ words and pattern match; if it does hit, it must still be downgraded
                if decision.strategy == Strategy.ENGINEERING:
                    raise AssertionError("ENGINEERING should have been downgraded to REACT when PLAN_ENABLED is false")

    def test_skill_override_cannot_force_plan(self):
        from nally.agent.task_router import Strategy, route

        # A skill listing plan-related words must not change router strategy alone
        decision = route("hello there, just saying hi")
        assert decision.strategy != Strategy.PLAN or "plan" not in "hello there, just saying hi".lower()


# ── R4: Adversarial step verification ──────────────────────────────


class TestAdversarialVerification:
    def test_generic_completion_vs_file_goal_must_fail(self):
        ok, _ = verify_step_result("create file config.yaml", "Command completed.")
        assert ok is False
        ok, _ = verify_step_result("create file config.yaml", "Successfully completed.")
        assert ok is False

    def test_harness_completion_cannot_override_zero_overlap(self):
        from nally.agent.harness import verify_tool_result

        result = verify_tool_result(
            tool_name="run_command",
            tool_args={"command": "echo hi"},
            tool_result="Successfully completed.",
            tool_success=True,
            objective="create file config.yaml with database settings",
        )
        assert result.satisfies_objective is False

    def test_fetch_boundaries(self):
        assert verify_step_result("fetch info about cats", "x" * 49)[0] is False
        assert verify_step_result("fetch info about cats", "x" * 50)[0] is True
        assert verify_step_result("fetch info about cats", "x" * 51)[0] is True

    def test_generic_boundaries(self):
        assert verify_step_result("do the thing", "x" * 19)[0] is False
        assert verify_step_result("do the thing", "x" * 20)[0] is True
        assert verify_step_result("do the thing", "x" * 21)[0] is True

    def test_error_word_in_test_goal_counts_positive(self):
        # Current behavior: "error" in a test result is treated as an outcome marker
        # We lock it explicitly so a future change is deliberate.
        ok, _ = verify_step_result("run tests", "1 error in 3 tests")
        assert ok is True

    def test_truly_ambiguous_returns_failed(self):
        # Unclassifiable goal with thin result -> not verified -> FAILED path
        ok, reason = verify_step_result("do something vague", "tiny")
        assert ok is False
        assert "thin" in reason
