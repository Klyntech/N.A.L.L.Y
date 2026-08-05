"""Tests for nally.agent.planner — simplified LangGraph planning pipeline."""

import json

from nally.agent.planner import (
    Plan,
    PlanStep,
    StepStatus,
    classify_by_patterns,
    parse_plan_response,
    route_after_classify,
    route_after_replan,
    validate_plan,
)

# ── Classification ────────────────────────────────────────


class TestClassifyByPatterns:
    def test_simple_greeting(self):
        assert classify_by_patterns("hey nally") == "simple"

    def test_simple_question(self):
        assert classify_by_patterns("what is the weather today") == "simple"

    def test_simple_explain(self):
        assert classify_by_patterns("explain what a closure is") == "simple"

    def test_plan_multi_action(self):
        text = "Build a REST API and then create a React frontend and also set up the database"
        assert classify_by_patterns(text) == "plan"

    def test_plan_explicit(self):
        text = "Give me a step by step plan to build and deploy this app"
        assert classify_by_patterns(text) == "plan"

    def test_plan_large_scope(self):
        text = "Build a full stack application from scratch with auth and payments"
        assert classify_by_patterns(text) == "plan"

    def test_simple_by_default(self):
        assert classify_by_patterns("remember that I like coffee") == "simple"


# ── Parsing ───────────────────────────────────────────────


class TestParsePlanResponse:
    def test_valid_json(self):
        response = json.dumps({
            "goal": "build an API",
            "steps": [
                {"id": "step_1", "goal": "Create endpoints"},
                {"id": "step_2", "goal": "Add auth"},
            ],
        })
        plan = parse_plan_response(response, "build an API")
        assert plan is not None
        assert plan.goal == "build an API"
        assert len(plan.steps) == 2
        assert plan.steps[0].id == "step_1"

    def test_json_in_markdown(self):
        response = 'Here is the plan:\n```json\n{"goal": "test", "steps": [{"id": "s1", "goal": "do stuff"}]}\n```'
        plan = parse_plan_response(response, "test")
        assert plan is not None
        assert len(plan.steps) == 1

    def test_invalid_json(self):
        plan = parse_plan_response("not json at all", "test")
        assert plan is None

    def test_missing_steps(self):
        response = json.dumps({"goal": "test"})
        plan = parse_plan_response(response, "test")
        assert plan is None

    def test_fallback_goal(self):
        response = json.dumps({"steps": [{"id": "s1", "goal": "do stuff"}]})
        plan = parse_plan_response(response, "my goal")
        assert plan is not None
        assert plan.goal == "my goal"


# ── Validation ────────────────────────────────────────────


class TestValidatePlan:
    def test_valid_plan_passes(self):
        plan = Plan(goal="test", steps=[
            PlanStep(id="s1", goal="step 1"),
            PlanStep(id="s2", goal="step 2"),
        ])
        result = validate_plan(plan)
        assert len(result.steps) == 2

    def test_truncate_to_max(self):
        steps = [PlanStep(id=f"s{i}", goal=f"step {i}") for i in range(15)]
        plan = Plan(goal="test", steps=steps)
        result = validate_plan(plan)
        assert len(result.steps) == 10


# ── Routing ───────────────────────────────────────────────


class TestRouting:
    def test_classify_plan_routes_to_planner(self):
        state = {"plan_status": "planning"}
        assert route_after_classify(state) == "planner"

    def test_classify_simple_routes_to_llm(self):
        state = {"plan_status": "none"}
        assert route_after_classify(state) == "llm"

    def test_replan_complete_routes_to_synthesize(self):
        plan = Plan(goal="test", steps=[PlanStep(id="s1", goal="step 1")])
        plan.steps[0].status = StepStatus.COMPLETED
        state = {"plan_status": "complete", "plan": plan}
        assert route_after_replan(state) == "synthesize"

    def test_replan_revising_routes_to_planner(self):
        state = {"plan_status": "revising", "plan": Plan(goal="test")}
        assert route_after_replan(state) == "planner"

    def test_replan_executing_routes_to_execute_step(self):
        plan = Plan(goal="test", steps=[
            PlanStep(id="s1", goal="step 1"),
            PlanStep(id="s2", goal="step 2"),
        ])
        plan.steps[0].status = StepStatus.COMPLETED
        state = {"plan_status": "executing", "plan": plan, "iteration": 0, "max_iterations": 100}
        assert route_after_replan(state) == "execute_step"
