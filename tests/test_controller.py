"""Tests for NallyController — deterministic Planning Judge edge cases."""

from nally.agent.controller import (
    NallyController,
    PlanTier,
    _decide_tier,
    _estimate_signals,
    get_controller,
)
from nally.agent.harness import Classification, TaskClass
from nally.agent.task_router import RouteDecision, Strategy


# ── Signal extraction ──────────────────────────────────────


def test_signals_simple_greeting():
    signals = _estimate_signals("hello", None)
    assert signals["step_count"] <= 1
    assert signals["tool_count"] == 0
    assert signals["high_stakes"] is False


def test_signals_multi_step():
    signals = _estimate_signals(
        "First set up the database, then create the API, and finally write tests", None
    )
    assert signals["step_count"] >= 3
    assert signals["dependencies"] >= 1


def test_signals_irreversible():
    signals = _estimate_signals("delete the production database", None)
    assert signals["irreversibility"] >= 2
    assert signals["high_stakes"] is True


def test_signals_high_stakes_keyword():
    signals = _estimate_signals("rotate the security credentials and deploy", None)
    assert signals["high_stakes"] is True


def test_signals_uncertain():
    c = Classification(TaskClass.AMBIGUOUS, 0.4, "unclear")
    signals = _estimate_signals("maybe do something?", c)
    assert signals["uncertainty"] >= 0.5


# ── Tier decision ──────────────────────────────────────────


def test_tier_none_for_simple():
    signals = _estimate_signals("hello", None)
    tier = _decide_tier(signals, "SIMPLE", Strategy.REACT)
    assert tier == PlanTier.NONE


def test_tier_full_for_high_stakes():
    signals = _estimate_signals("delete production database", None)
    tier = _decide_tier(signals, "HIGH_STAKES", Strategy.PLAN)
    assert tier == PlanTier.FULL


def test_tier_full_for_irreversible():
    signals = _estimate_signals("drop table users in production", None)
    tier = _decide_tier(signals, "COMPLEX", Strategy.PLAN)
    assert tier == PlanTier.FULL


def test_tier_light_for_moderate_complex():
    signals = _estimate_signals("build a login page with form validation", None)
    tier = _decide_tier(signals, "COMPLEX", Strategy.PLAN)
    assert tier in (PlanTier.LIGHT, PlanTier.FULL)


def test_tier_full_for_heavy_complex():
    signals = _estimate_signals(
        "build auth system with tests and deploy to production with migration", None
    )
    tier = _decide_tier(signals, "COMPLEX", Strategy.PLAN)
    assert tier == PlanTier.FULL


def test_tier_light_for_creative_with_steps():
    signals = _estimate_signals(
        "write a story: first chapter one, then chapter two, finally chapter three", None
    )
    tier = _decide_tier(signals, "CREATIVE", Strategy.PLAN)
    assert tier == PlanTier.LIGHT


def test_tier_none_for_simple_creative():
    signals = _estimate_signals("write a poem about rain", None)
    tier = _decide_tier(signals, "CREATIVE", Strategy.PLAN)
    assert tier == PlanTier.NONE


# ── Controller.decide() ────────────────────────────────────


def test_decide_simple_returns_react():
    ctrl = NallyController()
    c = Classification(TaskClass.SIMPLE, 0.95, "greeting")
    d = ctrl.decide("hello", classification=c)
    assert d.route.strategy == Strategy.REACT
    assert d.tier == PlanTier.NONE
    assert d.requires_approval is False
    assert d.max_steps == 0


def test_decide_complex_returns_plan():
    ctrl = NallyController()
    c = Classification(TaskClass.COMPLEX, 0.9, "multi-step")
    d = ctrl.decide(
        "build auth with tests and deploy to production", classification=c
    )
    assert d.route.strategy == Strategy.PLAN
    assert d.tier in (PlanTier.LIGHT, PlanTier.FULL)


def test_decide_high_stakes_forces_full_and_approval():
    ctrl = NallyController()
    c = Classification(TaskClass.HIGH_STAKES, 0.88, "risky")
    d = ctrl.decide("delete production database", classification=c)
    assert d.tier == PlanTier.FULL
    assert d.requires_approval is True
    assert d.max_steps > 0


def test_decide_irreversible_forces_full_and_approval():
    ctrl = NallyController()
    c = Classification(TaskClass.COMPLEX, 0.85, "destructive")
    d = ctrl.decide("drop table users in production", classification=c)
    assert d.tier == PlanTier.FULL
    assert d.requires_approval is True


def test_decide_light_tier_max_steps():
    ctrl = NallyController(light_cap=3, full_cap=8)
    c = Classification(TaskClass.COMPLEX, 0.8, "moderate")
    d = ctrl.decide("build a login page", classification=c)
    if d.tier == PlanTier.LIGHT:
        assert d.max_steps == 3
    elif d.tier == PlanTier.FULL:
        assert d.max_steps == 8


def test_decide_preserves_existing_route_decision():
    ctrl = NallyController()
    existing = RouteDecision(
        strategy=Strategy.PLAN,
        task_class="COMPLEX",
        confidence=0.9,
        reasoning="test",
        method="harness",
    )
    d = ctrl.decide("build something", route_decision=existing)
    assert d.route.strategy == Strategy.PLAN
    assert d.route.task_class == "COMPLEX"


def test_decide_promotes_react_to_plan_on_strong_signals():
    ctrl = NallyController()
    c = Classification(TaskClass.SIMPLE, 0.7, "simple")
    d = ctrl.decide(
        "First set up the database, then create the API, then write tests, then deploy",
        classification=c,
    )
    # Strong multi-step signals should promote to PLAN
    assert d.route.strategy == Strategy.PLAN


def test_decide_empty_input():
    ctrl = NallyController()
    d = ctrl.decide("", classification=None)
    assert d.route.strategy == Strategy.REACT
    assert d.tier == PlanTier.NONE


def test_decide_no_classification():
    ctrl = NallyController()
    d = ctrl.decide("do something complex with multiple steps", classification=None)
    # Should still produce a valid decision even without classification
    assert d.route is not None
    assert d.tier is not None


# ── Approval gate ──────────────────────────────────────────


def test_approval_gate_high_stakes_only_mode(monkeypatch):
    import os
    monkeypatch.setenv("NALLY_PLAN_REQUIRE_APPROVAL", "high_stakes_only")
    ctrl = NallyController()
    c = Classification(TaskClass.COMPLEX, 0.85, "multi-step")
    d = ctrl.decide("build auth system", classification=c)
    # COMPLEX without high_stakes signals should not require approval
    if d.tier != PlanTier.NONE and not d.signals.get("high_stakes"):
        assert d.requires_approval is False


def test_approval_gate_all_mode(monkeypatch):
    import os
    monkeypatch.setenv("NALLY_PLAN_REQUIRE_APPROVAL", "all")
    ctrl = NallyController()
    c = Classification(TaskClass.COMPLEX, 0.85, "multi-step")
    d = ctrl.decide("build auth system", classification=c)
    if d.tier != PlanTier.NONE:
        assert d.requires_approval is True


def test_approval_gate_none_mode(monkeypatch):
    import os
    monkeypatch.setenv("NALLY_PLAN_REQUIRE_APPROVAL", "none")
    ctrl = NallyController()
    c = Classification(TaskClass.HIGH_STAKES, 0.9, "risky")
    d = ctrl.decide("delete production database", classification=c)
    assert d.requires_approval is False


# ── PLAN_ENABLED kill-switch ───────────────────────────────


def test_plan_enabled_kill_switch(monkeypatch):
    import nally.config as cfg
    monkeypatch.setattr(cfg, "PLAN_ENABLED", False)
    ctrl = NallyController()
    c = Classification(TaskClass.COMPLEX, 0.9, "multi-step")
    d = ctrl.decide("build a full system with tests", classification=c)
    assert d.route.strategy == Strategy.REACT
    assert d.tier == PlanTier.NONE


# ── Singleton ──────────────────────────────────────────────


def test_singleton_returns_same_instance():
    a = get_controller()
    b = get_controller()
    assert a is b


def test_singleton_is_stateless():
    ctrl = get_controller()
    # Should not raise on concurrent calls (stateless, no mutation)
    c = Classification(TaskClass.SIMPLE, 0.9, "test")
    d1 = ctrl.decide("hello", classification=c)
    d2 = ctrl.decide("hello", classification=c)
    assert d1.tier == d2.tier
    assert d1.route.strategy == d2.route.strategy


# ── to_dict serialization ──────────────────────────────────


def test_decision_to_dict():
    ctrl = NallyController()
    c = Classification(TaskClass.HIGH_STAKES, 0.9, "risky")
    d = ctrl.decide("delete production database", classification=c)
    d_dict = d.to_dict()
    assert "tier" in d_dict
    assert "requires_approval" in d_dict
    assert "max_steps" in d_dict
    assert "strategy" in d_dict
    assert "controller_reasoning" in d_dict


# ── should_delegate ────────────────────────────────────────


def test_should_delegate_parallel_signals():
    ctrl = NallyController()
    assert ctrl.should_delegate("do task 1 and task 2 and task 3 in parallel") is True


def test_should_delegate_no_signals():
    ctrl = NallyController()
    assert ctrl.should_delegate("hello") is False
