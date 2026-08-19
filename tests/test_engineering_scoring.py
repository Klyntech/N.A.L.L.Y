"""Tests for approach parsing, category enforcement, scoring, and selection."""

from __future__ import annotations

import pytest

from nally.engineering.approaches import ensure_categories, parse_approaches
from nally.engineering.models import ApproachCategory, EngineeringError
from nally.engineering.scoring import (
    DEFAULT_WEIGHTS,
    merge_approaches,
    score_approaches,
    select_best,
    weighted_total,
)

_BRAINSTORM_JSON = """
{
  "approaches": [
    {"id":"a1","title":"Naive script","category":"simple",
     "summary":"One file, stdlib only","pros":["simple"],"cons":["limited"],
     "scores":{"feasibility":5,"simplicity":5,"maintainability":3,"performance":3,"novelty":2}},
    {"id":"a2","title":"Layered app","category":"robust_scalable",
     "summary":"Structured, tested","pros":["solid"],"cons":["more code"],
     "scores":{"feasibility":5,"simplicity":3,"maintainability":5,"performance":4,"novelty":3}},
    {"id":"a3","title":"Streaming pipeline","category":"creative_unconventional",
     "summary":"Treat files as a stream","pros":["novel"],"cons":["risky"],
     "scores":{"feasibility":3,"simplicity":2,"maintainability":3,"performance":5,"novelty":5}}
  ]
}
"""


def test_parse_approaches_three_categories():
    apps = parse_approaches(_BRAINSTORM_JSON)
    assert len(apps) == 3
    cats = {a.category for a in apps}
    assert ApproachCategory.SIMPLE in cats
    assert ApproachCategory.ROBUST in cats
    assert ApproachCategory.CREATIVE in cats
    # Scores carried through.
    assert apps[0].feasibility == 5
    assert apps[2].novelty == 5


def test_parse_approaches_empty_raises():
    with pytest.raises(EngineeringError):
        parse_approaches("{}")


def test_ensure_categories_fills_missing():
    partial = parse_approaches(
        '{"approaches":[{"id":"x","title":"Only simple","category":"simple",'
        '"scores":{"feasibility":5,"simplicity":5,"maintainability":4,"performance":3,"novelty":2}}]}'
    )
    filled = ensure_categories(partial)
    cats = {a.category for a in filled}
    assert len(cats) == 3
    assert any(a.id.startswith("fallback_") for a in filled)


def test_score_approaches_weighted_total():
    apps = parse_approaches(_BRAINSTORM_JSON)
    scores = score_approaches(apps)
    assert len(scores) == 3
    # Creative approach has highest novelty/performance; verify total is in range.
    for s in scores:
        assert 0.0 <= s.weighted_total <= 5.0
    # Deterministic: same input -> same output.
    scores2 = score_approaches(apps)
    assert [s.weighted_total for s in scores] == [s.weighted_total for s in scores2]


def test_weighted_total_matches_formula():
    from nally.engineering.models import ApproachScore

    s = ApproachScore("a", 4, 4, 4, 4, 4)
    expected = 4.0 * sum(DEFAULT_WEIGHTS.values())
    assert abs(weighted_total(s) - 4.0) < 1e-9
    assert abs(weighted_total(s) - expected) < 1e-9


def test_select_best_picks_highest():
    apps = parse_approaches(_BRAINSTORM_JSON)
    scores = score_approaches(apps)
    best = select_best(scores, apps)
    # The robust approach should win (high maintainability/feasibility blend).
    assert best.id == "a2"


def test_merge_approaches_combines_strengths():
    apps = parse_approaches(_BRAINSTORM_JSON)
    merged = merge_approaches(apps[1], apps[2], title="Hybrid")
    assert "Hybrid" in merged.title
    assert "novel" in merged.pros  # from creative
    assert "solid" in merged.pros  # from robust
    assert merged.category == ApproachCategory.ROBUST
