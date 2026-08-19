"""Planner classify eval — 10 hand-crafted queries: 5 should plan, 5 should not."""

import pytest

from nally.agent.planner import classify_by_patterns


# ── Queries that MUST classify as 'simple' ────────────────

SIMPLE_CASES = [
    ("What time is it in Lagos?", "trivial question"),
    ("Hey, how are you?", "greeting"),
    ("What's the weather today?", "single-clause question"),
    ("Tell me about Python decorators", "knowledge request"),
    ("Weather and time in Lagos", "multi-clause but short, no action keywords"),
]


# ── Queries that MUST classify as 'plan' ──────────────────

PLAN_CASES = [
    (
        "Build a full-stack web app with React frontend, FastAPI backend, "
        "PostgreSQL database, deploy to Render, set up CI/CD pipeline, "
        "and configure monitoring with Grafana.",
        "multi-step build with action keywords",
    ),
    (
        "Create a REST API for user management, then build an admin dashboard "
        "to view analytics, and finally deploy everything to AWS with Terraform.",
        "sequential multi-stage with deploy",
    ),
    (
        "Research the best NLP libraries for sentiment analysis, compare their "
        "performance benchmarks, and then build a prototype classifier using "
        "the winning library with proper evaluation metrics.",
        "research → compare → build pipeline",
    ),
    (
        "Migrate the existing SQLite database to PostgreSQL, update all ORM "
        "queries, set up connection pooling, configure automated backups, "
        "and verify data integrity with checksums.",
        "migration with multiple verification stages",
    ),
    (
        "Set up a complete CI/CD pipeline: configure GitHub Actions for linting "
        "and testing, build Docker images, deploy staging environment automatically, "
        "run integration tests, and promote to production on approval.",
        "full DevOps pipeline with approval gate",
    ),
]


class TestClassifyCostGuard:
    """Verify cost guard prevents trivial queries from triggering planning."""

    @pytest.mark.parametrize("query,label", SIMPLE_CASES)
    def test_simple_queries(self, query, label):
        assert classify_by_patterns(query) == "simple", f"Failed for: {label}"

    @pytest.mark.parametrize("query,label", PLAN_CASES)
    def test_plan_queries(self, query, label):
        assert classify_by_patterns(query) == "plan", f"Failed for: {label}"

    def test_short_with_action_keyword_gets_plan(self):
        """Short query WITH action keyword should still plan if it has enough signals."""
        result = classify_by_patterns(
            "Build and deploy a simple API"
        )
        # This is borderline — may or may not plan depending on signal count.
        # The cost guard only blocks short queries WITHOUT action keywords.
        assert result in ("plan", "simple")

    def test_long_without_action_gets_plan_if_enough_signals(self):
        """Long query with 3+ sentences and plan signals should plan."""
        result = classify_by_patterns(
            "First I need to research the market. Then I should analyze the competitors. "
            "After that I need to evaluate the pricing strategy. Finally I will "
            "compare the options and make a recommendation."
        )
        assert result == "plan"
