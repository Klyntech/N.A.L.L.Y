"""Approach scoring, selection, and merging.

Pure functions — no LLM, no IO. Each approach is scored 1..5 on five axes and
combined into a weighted total. Selection and merging are deterministic.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .models import Approach, ApproachCategory, ApproachScore, EngineeringError

DEFAULT_WEIGHTS: Dict[str, float] = {
    "feasibility": 0.30,
    "simplicity": 0.20,
    "maintainability": 0.20,
    "performance": 0.15,
    "novelty": 0.15,
}

_AXES = ("feasibility", "simplicity", "maintainability", "performance", "novelty")


def _clamp(value: object) -> float:
    try:
        v = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 3.0
    return max(0.0, min(5.0, v))


def score_approaches(
    approaches: List[Approach],
    weights: Optional[Dict[str, float]] = None,
    rationale: Optional[Dict[str, str]] = None,
) -> List[ApproachScore]:
    """Score every approach and compute its weighted total.

    Args:
        approaches: Approaches to score.
        weights: Axis weights (default :data:`DEFAULT_WEIGHTS`). Must sum to ~1.
        rationale: Optional per-approach rationale strings keyed by approach id.

    Returns:
        One :class:`ApproachScore` per approach, in input order.
    """
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        for k, v in weights.items():
            if k in w:
                w[k] = float(v)
    total_w = sum(w.values()) or 1.0
    # Normalize so weights always sum to 1 (defensive).
    w = {k: v / total_w for k, v in w.items()}

    scores: List[ApproachScore] = []
    for a in approaches:
        axis_values = {
            "feasibility": _clamp(a.feasibility),
            "simplicity": _clamp(a.simplicity),
            "maintainability": _clamp(a.maintainability),
            "performance": _clamp(a.performance),
            "novelty": _clamp(a.novelty),
        }
        # If the approach object did not carry scores, we cannot score it.
        any_scored = any(
            getattr(a, axis) is not None for axis in _AXES
        )
        if not any_scored:
            raise EngineeringError(
                f"Approach '{a.id}' has no scores; scoring requires LLM-provided axis values."
            )
        weighted = sum(axis_values[axis] * w.get(axis, 0.0) for axis in _AXES)
        scores.append(
            ApproachScore(
                approach_id=a.id,
                feasibility=axis_values["feasibility"],
                simplicity=axis_values["simplicity"],
                maintainability=axis_values["maintainability"],
                performance=axis_values["performance"],
                novelty=axis_values["novelty"],
                rationale=(rationale or {}).get(a.id, ""),
                weighted_total=weighted,
            )
        )
    return scores


def weighted_total(score: ApproachScore, weights: Optional[Dict[str, float]] = None) -> float:
    """Recompute the weighted total for a score (exposed for tests)."""
    w = dict(DEFAULT_WEIGHTS)
    if weights:
        for k, v in weights.items():
            if k in w:
                w[k] = float(v)
    total_w = sum(w.values()) or 1.0
    w = {k: v / total_w for k, v in w.items()}
    return (
        score.feasibility * w.get("feasibility", 0.0)
        + score.simplicity * w.get("simplicity", 0.0)
        + score.maintainability * w.get("maintainability", 0.0)
        + score.performance * w.get("performance", 0.0)
        + score.novelty * w.get("novelty", 0.0)
    )


def select_best(
    scored: List[ApproachScore],
    approaches: List[Approach],
    strategy: str = "weighted",
) -> Approach:
    """Return the winning :class:`Approach`.

    ``strategy`` is currently ``weighted`` (highest weighted_total, tie-broken
    by feasibility then novelty). Returns the first approach if scoring is empty.
    """
    if not scored:
        if approaches:
            return approaches[0]
        raise EngineeringError("Cannot select from empty approaches")
    by_id = {a.id: a for a in approaches}
    ranked = sorted(
        scored,
        key=lambda s: (s.weighted_total, s.feasibility, s.novelty),
        reverse=True,
    )
    best = ranked[0]
    return by_id.get(best.approach_id, approaches[0])


def merge_approaches(
    primary: Approach,
    secondary: Approach,
    title: Optional[str] = None,
) -> Approach:
    """Merge two approaches, keeping primary's description but blending strengths.

    Pros/cons/risks are concatenated (de-duplicated) and technologies unioned.
    Useful when the best design is a hybrid of, say, the robust and creative
    proposals.
    """
    merged_pros = _unique(primary.pros + secondary.pros)
    merged_cons = _unique(primary.cons + secondary.cons)
    merged_risks = _unique(primary.risks + secondary.risks)
    merged_tech = _unique(primary.technologies + secondary.technologies)
    return Approach(
        id=f"merged_{primary.id}_{secondary.id}",
        title=title or f"Merged: {primary.title} + {secondary.title}",
        category=ApproachCategory.ROBUST,
        summary=f"{primary.summary} (merged with elements of: {secondary.title})",
        description=primary.description or secondary.description,
        pros=merged_pros,
        cons=merged_cons,
        risks=merged_risks,
        technologies=merged_tech,
    )


def _unique(items: List[str]) -> List[str]:
    seen = set()
    out: List[str] = []
    for it in items:
        key = it.strip().lower()
        if key and key not in seen:
            seen.add(key)
            out.append(it.strip())
    return out
