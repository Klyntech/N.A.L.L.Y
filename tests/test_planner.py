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
    execute_step_node,
    parse_plan_response,
    planner_node,
    route_after_classify,
    route_after_critique,
    route_after_planner,
    route_after_replan,
    synthesize_node,
    validate_plan,
)
from nally.config import PLAN_MAX_REVISIONS

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

    def test_replan_rejected_routes_to_synthesize(self):
        plan = Plan(goal="test", steps=[PlanStep(id="s1", goal="step 1")])
        state = {"plan_status": "rejected", "plan": plan}
        assert route_after_replan(state) == "synthesize"

    def test_replan_partial_routes_to_synthesize(self):
        plan = Plan(goal="test", steps=[PlanStep(id="s1", goal="step 1")])
        state = {"plan_status": "partial", "plan": plan}
        assert route_after_replan(state) == "synthesize"

    def test_replan_failed_routes_to_synthesize(self):
        plan = Plan(goal="test", steps=[PlanStep(id="s1", goal="step 1")])
        state = {"plan_status": "failed", "plan": plan}
        assert route_after_replan(state) == "synthesize"

    def test_cap_exhaustion_partial_when_some_completed(self):
        from nally.agent.planner import _replan_decision

        plan = Plan(
            goal="test",
            steps=[PlanStep(id="s1", goal="ok"), PlanStep(id="s2", goal="bad")],
        )
        plan.steps[0].status = StepStatus.COMPLETED
        plan.steps[1].status = StepStatus.FAILED
        plan.revision_count = PLAN_MAX_REVISIONS
        state = {"plan": plan, "iteration": 0, "max_iterations": 100}
        result = _replan_decision(state)
        assert result["plan_status"] == "partial"
        assert plan.status == PlanStatus.PARTIAL

    def test_cap_exhaustion_failed_when_none_completed(self):
        from nally.agent.planner import _replan_decision

        plan = Plan(goal="test", steps=[PlanStep(id="s1", goal="bad")])
        plan.steps[0].status = StepStatus.FAILED
        plan.revision_count = PLAN_MAX_REVISIONS
        state = {"plan": plan, "iteration": 0, "max_iterations": 100}
        assert _replan_decision(state)["plan_status"] == "failed"

    def test_iteration_cap_never_manufactures_complete(self):
        from nally.agent.planner import _replan_decision

        plan = Plan(goal="test", steps=[PlanStep(id="s1", goal="bad")])
        plan.steps[0].status = StepStatus.FAILED
        state = {"plan": plan, "iteration": 99, "max_iterations": 100}
        result = _replan_decision(state)
        assert result["plan_status"] in ("partial", "failed", "revising")
        assert result["plan_status"] != "complete"

    def test_unknown_status_never_executes(self):
        plan = Plan(goal="test", steps=[PlanStep(id="s1", goal="step 1")])
        state = {"plan_status": "foo", "plan": plan}
        assert route_after_replan(state) == "synthesize"

    def test_executing_without_pending_terminates(self):
        plan = Plan(goal="test", steps=[PlanStep(id="s1", goal="step 1")])
        plan.steps[0].status = StepStatus.COMPLETED
        state = {"plan_status": "executing", "plan": plan, "iteration": 0, "max_iterations": 100}
        assert route_after_replan(state) == "synthesize"


class TestPlannerOutcomeSplit:
    """PLAN_READY goes to critique; PLAN_FAILED goes to ReAct, never critique."""

    def test_plan_failed_routes_to_llm(self):
        assert route_after_planner({"plan_status": "plan_failed", "plan": None}) == "llm"

    def test_missing_plan_routes_to_llm(self):
        assert route_after_planner({"plan_status": "executing", "plan": None}) == "llm"

    def test_ready_plan_routes_to_critique(self):
        plan = Plan(goal="test", steps=[PlanStep(id="s1", goal="step 1")])
        state = {"plan_status": "executing", "plan": plan}
        assert route_after_planner(state) == "critique"

    def test_planner_llm_failure_returns_plan_failed(self):
        state = {
            "messages": [HumanMessage(content="build a widget")],
            "thread_id": "test-plan-failed",
        }
        with patch("nally.agent.llm.llm") as mock_llm:
            mock_llm.simple_chat.side_effect = Exception("no network")
            result = planner_node(dict(state))
        assert result["plan_status"] == "plan_failed"
        assert result["plan"] is None

    def test_planner_bad_json_returns_plan_failed(self):
        state = {
            "messages": [HumanMessage(content="build a widget")],
            "thread_id": "test-plan-badjson",
        }
        with patch("nally.agent.llm.llm") as mock_llm:
            mock_llm.simple_chat.return_value = "not json at all"
            result = planner_node(dict(state))
        assert result["plan_status"] == "plan_failed"
        assert result["plan"] is None

    def test_execute_step_without_plan_stops(self):
        result = execute_step_node({"thread_id": "t", "plan": None})
        assert result["plan_status"] == "plan_failed"
        assert result["plan"] is None


class TestSynthesizeTerminals:
    """Synthesize renders DONE/PARTIAL/BLOCKED/FAILED distinctly."""

    def _make_state(self, terminal, completed=True):
        from nally.agent.planner import _plan_to_state

        plan = Plan(goal="test goal", steps=[PlanStep(id="s1", goal="step 1")])
        plan.steps[0].status = StepStatus.COMPLETED if completed else StepStatus.FAILED
        plan.steps[0].result = "did the thing"
        state = _plan_to_state({"messages": []}, plan)
        state["plan_status"] = terminal
        return state

    def _run(self, terminal, completed=True):
        with patch("nally.agent.llm.llm") as mock_llm:
            mock_llm.simple_chat.return_value = "synthesized"
            result = synthesize_node(self._make_state(terminal, completed))
        call = mock_llm.simple_chat.call_args
        prompt = call.kwargs.get("user_message", "")
        if not prompt and call.args:
            prompt = call.args[0]
        return result, prompt

    def test_complete_preserved(self):
        result, prompt = self._run("complete")
        assert result["plan_status"] == "complete"
        assert "Outcome of this plan: COMPLETE" in prompt

    def test_partial_rendered_distinctly(self):
        result, prompt = self._run("partial")
        assert result["plan_status"] == "partial"
        assert "WHAT COMPLETED" in prompt
        assert "WHAT REMAINS" in prompt

    def test_failed_rendered_distinctly(self):
        result, prompt = self._run("failed", completed=False)
        assert result["plan_status"] == "failed"
        assert "could not be completed" in prompt

    def test_rejected_renders_as_blocked(self):
        result, prompt = self._run("rejected", completed=False)
        assert result["plan_status"] == "blocked"
        assert "Outcome of this plan: BLOCKED" in prompt
        assert "blocking condition" in prompt


class TestStepGoalVerification:
    """ok=True alone never completes a step; evidence does."""

    def test_error_result_never_verifies(self):
        from nally.agent.planner import verify_step_result

        ok, _ = verify_step_result("create file x.py", "Error: write failed")
        assert ok is False

    def test_empty_result_never_verifies(self):
        from nally.agent.planner import verify_step_result

        ok, _ = verify_step_result("do the thing", "   ")
        assert ok is False

    def test_file_goal_requires_existing_file(self, tmp_path):
        from nally.agent.planner import verify_step_result

        target = tmp_path / "made.py"
        ok, _ = verify_step_result(f"create file {target}", "wrote it")
        assert ok is False
        target.write_text("x = 1\n")
        ok, reason = verify_step_result(f"create file {target}", "wrote it")
        assert ok is True
        assert "exists" in reason

    def test_file_goal_without_path_is_unknown(self):
        from nally.agent.planner import verify_step_result

        ok, _ = verify_step_result("create file with stuff", "wrote it")
        assert ok is False

    def test_test_goal_requires_outcome(self):
        from nally.agent.planner import verify_step_result

        ok, _ = verify_step_result("run tests", "all meaningless prose here")
        assert ok is False
        ok, _ = verify_step_result("run pytest", "3 passed in 1.2s")
        assert ok is True

    def test_fetch_goal_requires_substance(self):
        from nally.agent.planner import verify_step_result

        ok, _ = verify_step_result("fetch info about cats", "tiny")
        assert ok is False
        ok, _ = verify_step_result("fetch info about cats", "x" * 60)
        assert ok is True

    def test_unverified_step_marks_failed(self):
        from nally.agent.planner import _get_plan, _plan_to_state

        plan = Plan(goal="g", steps=[PlanStep(id="s1", goal="create file ghost_xyz.py")])
        state = _plan_to_state({"thread_id": "t"}, plan)
        with patch("nally.agent.planner._execute_step", return_value="wrote it"):
            result = execute_step_node(state)
        out = _get_plan(result)
        assert out.steps[0].status == StepStatus.FAILED
        assert "verification failed" in (out.steps[0].error or "")
        assert result.get("plan_status") != "complete"

    def test_verified_step_completes(self, tmp_path):
        from nally.agent.planner import _get_plan, _plan_to_state

        target = tmp_path / "real.py"
        target.write_text("x = 1\n")
        plan = Plan(goal="g", steps=[PlanStep(id="s1", goal=f"create file {target}")])
        state = _plan_to_state({"thread_id": "t"}, plan)
        with patch("nally.agent.planner._execute_step", return_value="wrote it"):
            result = execute_step_node(state)
        assert _get_plan(result).steps[0].status == StepStatus.COMPLETED


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

    def test_no_plan_returns_complete(self):
        state = {"plan": None}
        result = critique_node(state)
        assert result["plan_status"] == "complete"

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

