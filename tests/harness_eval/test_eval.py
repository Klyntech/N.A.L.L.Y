"""Pytest integration for Harness Evaluation Runner.

Runs the eval cases as pytest tests so they're part of the regular test suite.
Each eval case becomes a separate test function for granular reporting.
"""

import json
from pathlib import Path

import pytest

from .runner import load_cases, run_eval_case


# Load all cases at module level
_CASES_DIR = str(Path(__file__).parent / "cases")
_ALL_CASES = load_cases(_CASES_DIR)


@pytest.fixture(scope="session")
def eval_cases():
    """Provide all loaded eval cases."""
    return _ALL_CASES


def _make_test_id(case):
    """Generate a readable test ID from a case."""
    return f"{case.id}_{case.task_class}"


@pytest.mark.parametrize(
    "case",
    _ALL_CASES,
    ids=[_make_test_id(c) for c in _ALL_CASES],
)
def test_harness_eval(case):
    """Run a single harness evaluation case."""
    result = run_eval_case(case)

    # Class match is required
    assert result.class_match, (
        f"Classification mismatch: expected {case.task_class}, "
        f"got {result.actual_class} for input: {case.input[:80]}"
    )

    # Pass criteria must be met
    assert result.pass_criteria_met, (
        f"Pass criteria not met for {case.id}: {case.pass_criteria}"
    )

    # No errors during classification
    assert result.error is None, (
        f"Error during classification: {result.error}"
    )


class TestHarnessEvalSummary:
    """Summary tests that run after all individual cases."""

    def test_all_cases_loaded(self):
        """Verify test cases were loaded from JSON files."""
        assert len(_ALL_CASES) > 0, "No eval cases found"

    def test_case_coverage(self):
        """Verify we have cases for all major task classes."""
        classes_covered = set(c.task_class for c in _ALL_CASES)
        assert "SIMPLE" in classes_covered
        assert "COMPLEX" in classes_covered
        assert "CREATIVE" in classes_covered
        assert "HIGH_STAKES" in classes_covered

    def test_injection_cases_present(self):
        """Verify adversarial/injection test cases exist."""
        injection_cases = [c for c in _ALL_CASES if "injection" in c.id]
        assert len(injection_cases) >= 2, "Need at least 2 injection test cases"

    def test_tool_failure_cases_present(self):
        """Verify tool failure test cases exist."""
        fail_cases = [c for c in _ALL_CASES if "tool_fail" in c.id]
        assert len(fail_cases) >= 1, "Need at least 1 tool failure test case"
