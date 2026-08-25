"""Tests for nally.agent.planner — simplified LangGraph planning pipeline."""

import json
from unittest.mock import MagicMock, patch

from langchain_core.messages import HumanMessage

from nally.agent.planner import (
    Plan,
    PlanStatus,
    PlanStep,
    StepStatus,
    _get_plan,
    _plan_to_state,
    classify_by_patterns,
    critique_node,
    parse_plan_response,
    route_after_classify,
    route_after_critique,
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
        response = json.dumps(
            {
                "goal": "build an API",
                "steps": [
                    {"id": "step_1", "goal": "Create endpoints"},
                    {"id": "step_2", "goal": "Add auth"},
                ],
            }
        )
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
        plan = Plan(
            goal="test",
            steps=[
                PlanStep(id="s1", goal="step 1"),
                PlanStep(id="s2", goal="step 2"),
            ],
        )
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
        plan = Plan(
            goal="test",
            steps=[
                PlanStep(id="s1", goal="step 1"),
                PlanStep(id="s2", goal="step 2"),
            ],
        )
        plan.steps[0].status = StepStatus.COMPLETED
        state = {"plan_status": "executing", "plan": plan, "iteration": 0, "max_iterations": 100}
        assert route_after_replan(state) == "execute_step"


# ── Critique Node ─────────────────────────────────────────


class TestCritiqueNode:
    """Tests for the plan critique node (reviews plans before execution)."""

    def _make_plan(self, goal="build an API", step_count=2):
        steps = [PlanStep(id=f"s{i}", goal=f"step {i}") for i in range(step_count)]
        return Plan(goal=goal, steps=steps)

    def _make_state(self, plan=None, revision_count=0):
        p = plan or self._make_plan()
        p.revision_count = revision_count
        return {"plan": p, "plan_status": "executing"}

    @patch("nally.agent.llm.llm")
    def test_approve_verdict(self, mock_llm):
        mock_llm.simple_chat.return_value = json.dumps({"verdict": "approve"})
        state = self._make_state()
        result = critique_node(state)

        assert result["plan_status"] == "executing"
        # Plan is stored as dict in state for checkpoint serialization
        assert isinstance(result["plan"], dict)
        assert result["plan"]["critique"] is None

    @patch("nally.agent.llm.llm")
    def test_revise_verdict(self, mock_llm):
        mock_llm.simple_chat.return_value = json.dumps(
            {"verdict": "revise", "reason": "Missing a testing step"}
        )
        state = self._make_state()
        result = critique_node(state)

        assert result["plan_status"] == "critique_revising"
        assert isinstance(result["plan"], dict)
        assert result["plan"]["status"] == "revising"
        assert result["plan"]["critique"] == "Missing a testing step"

    @patch("nally.agent.llm.llm")
    def test_skip_when_revision_limit_reached(self, mock_llm):
        from nally.config import PLAN_MAX_REVISIONS

        state = self._make_state(revision_count=PLAN_MAX_REVISIONS)
        result = critique_node(state)

        assert result["plan_status"] == "executing"
        mock_llm.simple_chat.assert_not_called()

    @patch("nally.agent.llm.llm")
    def test_llm_error_fails_open(self, mock_llm):
        mock_llm.simple_chat.side_effect = Exception("LLM down")
        state = self._make_state()
        result = critique_node(state)

        assert result["plan_status"] == "executing"

    @patch("nally.agent.llm.llm")
    def test_unparseable_response_fails_open(self, mock_llm):
        mock_llm.simple_chat.return_value = "not json at all"
        state = self._make_state()
        result = critique_node(state)

        assert result["plan_status"] == "executing"

    def test_no_plan_returns_none(self):
        state = {"plan": None}
        result = critique_node(state)
        assert result["plan_status"] == "none"

    def test_route_after_critique_approve(self):
        state = {"plan_status": "executing"}
        assert route_after_critique(state) == "execute_step"

    def test_route_after_critique_revise(self):
        state = {"plan_status": "critique_revising"}
        assert route_after_critique(state) == "planner"


class TestPlannerNodeCritique:
    """Test that planner_node consumes plan.critique and builds the right prompt."""

    @patch("nally.agent.llm.llm")
    def test_critique_repair_prompt(self, mock_llm):
        """When existing_plan has status=REVISING and critique set, planner_node
        builds the critique-repair prompt (not the failure-repair prompt)."""
        from nally.agent.planner import planner_node

        mock_llm.simple_chat.return_value = json.dumps(
            {"goal": "test", "steps": [{"id": "s1", "goal": "step 1"}]}
        )
        existing = Plan(goal="test", steps=[PlanStep(id="s1", goal="step 1")])
        existing.status = PlanStatus.REVISING
        existing.critique = "Missing a testing step"

        state = {
            "messages": [HumanMessage(content="Build a test project")],
            "plan": existing,
            "plan_status": "revising",
        }
        result = planner_node(state)

        # The critique was consumed when building the prompt (cleared on the original)
        assert existing.critique is None
        # The LLM was called with the critique-repair prompt
        mock_llm.simple_chat.assert_called_once()
        prompt_arg = mock_llm.simple_chat.call_args[1]["user_message"]
        assert "reviewed and needs revision" in prompt_arg
        assert "Missing a testing step" in prompt_arg
        # A new plan was returned (revision count incremented)
        assert isinstance(result["plan"], dict)
        assert result["plan"]["revision_count"] == 1


# ── Serialization Round-Trip ───────────────────────────────


class TestPlanSerializationRoundTrip:
    """Verify Plan.to_dict() / Plan.from_dict() are inverse operations
    and that dicts (as stored in LangGraph state) survive msgpack-style
    serialization without TypeError."""

    def _make_full_plan(self):
        s1 = PlanStep(id="step_1", goal="Create endpoints")
        s1.status = StepStatus.COMPLETED
        s1.result = "Created 5 endpoints"

        s2 = PlanStep(id="step_2", goal="Add auth")
        s2.status = StepStatus.FAILED
        s2.error = "OAuth provider down"

        s3 = PlanStep(id="step_3", goal="Write tests")
        # PENDING by default

        plan = Plan(goal="build an API", steps=[s1, s2, s3])
        plan.status = PlanStatus.ACTIVE
        plan.revision_count = 2
        plan.summary = "Partial progress"
        plan.critique = "Missing error handling"
        return plan

    def test_to_dictProducesPlainTypes(self):
        """to_dict() output contains only JSON-safe types (str/int/list/dict/None)."""
        plan = self._make_full_plan()
        d = plan.to_dict()
        assert isinstance(d, dict)
        assert isinstance(d["steps"], list)
        for step in d["steps"]:
            assert isinstance(step, dict)
            for v in step.values():
                assert isinstance(v, (str, int, type(None)))

    def test_from_dictRoundTrip(self):
        """Plan -> to_dict -> from_dict recovers all fields."""
        original = self._make_full_plan()
        recovered = Plan.from_dict(original.to_dict())

        assert recovered.goal == original.goal
        assert recovered.status == original.status
        assert recovered.revision_count == original.revision_count
        assert recovered.summary == original.summary
        assert recovered.critique == original.critique
        assert recovered.created_at == original.created_at
        assert len(recovered.steps) == len(original.steps)

        for orig_s, recv_s in zip(original.steps, recovered.steps):
            assert recv_s.id == orig_s.id
            assert recv_s.goal == orig_s.goal
            assert recv_s.status == orig_s.status
            assert recv_s.result == orig_s.result
            assert recv_s.error == orig_s.error

    def test_get_planFromDictState(self):
        """_get_plan converts a dict in state back to a Plan object."""
        plan = self._make_full_plan()
        state = {"plan": plan.to_dict()}
        result = _get_plan(state)
        assert isinstance(result, Plan)
        assert result.goal == plan.goal

    def test_get_planFromNone(self):
        """_get_plan returns None when plan is None."""
        assert _get_plan({"plan": None}) is None
        assert _get_plan({}) is None

    def test_get_planPassthroughLiveObject(self):
        """_get_plan passes through a live Plan object unchanged."""
        plan = self._make_full_plan()
        result = _get_plan({"plan": plan})
        assert result is plan

    def test_plan_to_stateStoresDict(self):
        """_plan_to_state always stores a dict (or None), never a Plan."""
        plan = self._make_full_plan()
        state = _plan_to_state({}, plan)
        assert isinstance(state["plan"], dict)
        assert state["plan"]["goal"] == plan.goal

        state_none = _plan_to_state({}, None)
        assert state_none["plan"] is None

    def test_msgpackSerializable(self):
        """The dict produced by Plan.to_dict() can survive msgpack round-trip.

        This is the actual failure mode: SqliteSaver uses msgpack, which
        cannot serialize arbitrary Python objects.
        """
        try:
            import msgpack
        except ImportError:
            import pytest
            pytest.skip("msgpack not installed")

        plan = self._make_full_plan()
        state = _plan_to_state({}, plan)

        # This would raise TypeError for live Plan objects
        packed = msgpack.packb(state["plan"])
        unpacked = msgpack.unpackb(packed, raw=False)

        # Recover plan from the msgpack output
        recovered = Plan.from_dict(unpacked)
        assert recovered.goal == plan.goal
        assert len(recovered.steps) == 3
        assert recovered.steps[0].status == StepStatus.COMPLETED
        assert recovered.steps[1].status == StepStatus.FAILED

    def test_sqliteCheckpointRoundTrip(self):
        """Simulate a LangGraph SqliteSaver checkpoint save + load cycle."""
        import sqlite3

        plan = self._make_full_plan()
        state = _plan_to_state({}, plan)

        # Simulate what the checkpointer does: serialize and deserialize
        # SqliteSaver stores blobs (pickled or msgpacked).
        # We test with json as a simpler proxy that has the same type constraints.
        import json as _json

        serialized = _json.dumps(state["plan"])
        deserialized = _json.loads(serialized)
        recovered = Plan.from_dict(deserialized)

        assert recovered.goal == plan.goal
        assert recovered.steps[0].result == "Created 5 endpoints"
        assert recovered.steps[1].error == "OAuth provider down"

