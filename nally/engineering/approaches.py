"""Approach parsing and category enforcement for the brainstorm stage.

Guarantees the loop always has at least the three required design families
(simple / robust-scalable / creative-unconventional), synthesizing a fallback
for any missing category so downstream scoring never breaks.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ._json import extract_json
from .models import Approach, ApproachCategory, EngineeringError


def parse_approaches(text: str) -> List[Approach]:
    """Parse an LLM response into a list of :class:`Approach` objects."""
    if not text or not text.strip():
        raise EngineeringError("Empty approaches response")

    data = extract_json(text)

    raw_list: List[Any] = []
    if isinstance(data, list):
        raw_list = data
    elif isinstance(data, dict):
        raw_list = data.get("approaches") or data.get("options") or []
        if isinstance(data.get("approach"), dict):
            raw_list = [data["approach"]]

    if not isinstance(raw_list, list) or not raw_list:
        raise EngineeringError("No approaches found in LLM response")

    approaches: List[Approach] = []
    for i, item in enumerate(raw_list):
        if not isinstance(item, dict):
            continue
        cat = _coerce_category(item.get("category"))
        title = str(item.get("title") or item.get("name") or f"Approach {i + 1}")
        approach = Approach(
            id=str(item.get("id") or f"approach_{i + 1}"),
            title=title,
            category=cat,
            summary=str(item.get("summary") or item.get("description") or "")[:500],
            description=str(item.get("description") or item.get("summary") or ""),
            pros=_as_str_list(item.get("pros")),
            cons=_as_str_list(item.get("cons")),
            risks=_as_str_list(item.get("risks")),
            technologies=_as_str_list(item.get("technologies") or item.get("tech")),
            feasibility=_score_of(item, "feasibility"),
            simplicity=_score_of(item, "simplicity"),
            maintainability=_score_of(item, "maintainability"),
            performance=_score_of(item, "performance"),
            novelty=_score_of(item, "novelty"),
        )
        approaches.append(approach)

    if not approaches:
        raise EngineeringError("Failed to parse any valid approach")
    return approaches


def ensure_categories(approaches: List[Approach]) -> List[Approach]:
    """Ensure at least one approach exists per required category.

    Missing categories are filled with a conservative synthesized fallback so
    scoring and selection always have a full slate to choose from.
    """
    present = {a.category for a in approaches}
    required = [
        ApproachCategory.SIMPLE,
        ApproachCategory.ROBUST,
        ApproachCategory.CREATIVE,
    ]
    out = list(approaches)
    for cat in required:
        if cat not in present:
            out.append(_fallback_approach(cat))
    return out


def _coerce_category(value: Any) -> ApproachCategory:
    if not value:
        return ApproachCategory.SIMPLE
    v = str(value).strip().lower().replace(" ", "_").replace("-", "_")
    mapping = {
        "simple": ApproachCategory.SIMPLE,
        "naive": ApproachCategory.SIMPLE,
        "minimal": ApproachCategory.SIMPLE,
        "robust": ApproachCategory.ROBUST,
        "robust_scalable": ApproachCategory.ROBUST,
        "robustscalable": ApproachCategory.ROBUST,
        "scalable": ApproachCategory.ROBUST,
        "production": ApproachCategory.ROBUST,
        "creative": ApproachCategory.CREATIVE,
        "creative_unconventional": ApproachCategory.CREATIVE,
        "creativeunconventional": ApproachCategory.CREATIVE,
        "unconventional": ApproachCategory.CREATIVE,
        "experimental": ApproachCategory.CREATIVE,
        "bold": ApproachCategory.CREATIVE,
    }
    return mapping.get(v, ApproachCategory.SIMPLE)


def _fallback_approach(cat: ApproachCategory) -> Approach:
    if cat == ApproachCategory.SIMPLE:
        return Approach(
            id="fallback_simple",
            title="Simple single-file implementation",
            category=ApproachCategory.SIMPLE,
            summary="Minimal, dependency-light solution focusing on the core requirement.",
            description="Implement the smallest thing that satisfies the stated goal using built-in facilities only.",
            pros=["Easy to understand", "Fast to ship", "Few moving parts"],
            cons=["Limited extensibility", "May not scale"],
            risks=["Under-engineered for future needs"],
            technologies=[],
        )
    if cat == ApproachCategory.ROBUST:
        return Approach(
            id="fallback_robust",
            title="Robust and scalable implementation",
            category=ApproachCategory.ROBUST,
            summary="Structured solution with clear separation of concerns and error handling.",
            description="Layered design with configuration, validation, logging, and tests for maintainability.",
            pros=["Maintainable", "Handles edge cases", "Easier to extend"],
            cons=["More code", "Slower to build"],
            risks=["Over-engineering if scope is small"],
            technologies=[],
        )
    return Approach(
        id="fallback_creative",
        title="Creative unconventional approach",
        category=ApproachCategory.CREATIVE,
        summary="Novel angle using analogy or constraint inversion to differentiate the solution.",
        description="Re-frame the problem (e.g. treat files as a stream, or invert the control flow) for a surprising but valid result.",
        pros=["Differentiated", "Sparks new ideas", "Potential for elegance"],
        cons=["Riskier", "May need more explanation", "Less conventional tooling"],
        risks=["Could be harder to maintain"],
        technologies=[],
    )


def _score_of(item: Dict[str, Any], axis: str) -> Optional[float]:
    """Read a 1..5 axis score from an approach dict, tolerating a 'scores' sub-object."""
    val = item.get(axis)
    if val is None:
        scores = item.get("scores")
        if isinstance(scores, dict):
            val = scores.get(axis)
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(5.0, f))


def _as_str_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split("\n") if v.strip()]
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value)]
