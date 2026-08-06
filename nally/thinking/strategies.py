from dataclasses import dataclass
from enum import StrEnum
from typing import Dict, List, Optional


class StrategyDomain(StrEnum):
    CODE = "code"
    LIFE = "life"
    BUSINESS = "business"
    ALL = "all"


class StrategyCategory(StrEnum):
    DECISION = "decision"
    RISK = "risk"
    CREATIVE = "creative"
    ANALYTICAL = "analytical"
    STRUCTURAL = "structural"


@dataclass
class StrategyResult:
    strategy_name: str
    domain: str
    category: str
    analysis: str
    confidence: float = 0.5
    key_insight: str = ""
    recommendation: str = ""


STRATEGY_REGISTRY: Dict[str, Dict] = {
    "decision_matrix": {
        "name": "Decision Matrix",
        "description": "Weighted pros/cons analysis with scores",
        "domain": StrategyDomain.LIFE,
        "category": StrategyCategory.DECISION,
        "prompt_key": "decision_matrix",
    },
    "pre_mortem": {
        "name": "Pre-mortem",
        "description": "Assume failure, then identify why",
        "domain": StrategyDomain.ALL,
        "category": StrategyCategory.RISK,
        "prompt_key": "pre_mortem",
    },
    "second_order": {
        "name": "Second-Order Thinking",
        "description": "Analyze cascading consequences",
        "domain": StrategyDomain.ALL,
        "category": StrategyCategory.ANALYTICAL,
        "prompt_key": "second_order",
    },
    "six_hats": {
        "name": "Six Thinking Hats",
        "description": "Parallel perspectives: data, emotion, caution, optimism, creativity, process",
        "domain": StrategyDomain.ALL,
        "category": StrategyCategory.ANALYTICAL,
        "prompt_key": "six_hats",
    },
    "scampER": {
        "name": "SCAMPER",
        "description": "Substitute, Combine, Adapt, Modify, Put, Eliminate, Reverse",
        "domain": StrategyDomain.ALL,
        "category": StrategyCategory.CREATIVE,
        "prompt_key": "scampER",
    },
    "devils_advocate": {
        "name": "Devil's Advocate",
        "description": "Argue the opposite position to find flaws",
        "domain": StrategyDomain.ALL,
        "category": StrategyCategory.ANALYTICAL,
        "prompt_key": "devils_advocate",
    },
    "first_principles": {
        "name": "First Principles",
        "description": "Break down to fundamentals and rebuild",
        "domain": StrategyDomain.ALL,
        "category": StrategyCategory.ANALYTICAL,
        "prompt_key": "first_principles",
    },
    "inversion": {
        "name": "Inversion",
        "description": "How to guarantee failure, then invert",
        "domain": StrategyDomain.ALL,
        "category": StrategyCategory.RISK,
        "prompt_key": "inversion",
    },
    "swot": {
        "name": "SWOT Analysis",
        "description": "Strengths, Weaknesses, Opportunities, Threats",
        "domain": StrategyDomain.BUSINESS,
        "category": StrategyCategory.STRUCTURAL,
        "prompt_key": "swot",
    },
    "tradeoff_matrix": {
        "name": "Tradeoff Matrix",
        "description": "Gain vs sacrifice analysis with reversibility",
        "domain": StrategyDomain.ALL,
        "category": StrategyCategory.DECISION,
        "prompt_key": "tradeoff_matrix",
    },
    "edge_case_analysis": {
        "name": "Edge Case Analysis",
        "description": "Identify boundary conditions and failure modes",
        "domain": StrategyDomain.CODE,
        "category": StrategyCategory.STRUCTURAL,
        "prompt_key": "edge_case_analysis",
    },
    "lateral_thinking": {
        "name": "Lateral Thinking",
        "description": "Approach from unexpected angles and random connections",
        "domain": StrategyDomain.ALL,
        "category": StrategyCategory.CREATIVE,
        "prompt_key": "lateral_thinking",
    },
}


def get_strategy_names() -> List[str]:
    return list(STRATEGY_REGISTRY.keys())


def get_strategy(strategy_name: str) -> Optional[Dict]:
    return STRATEGY_REGISTRY.get(strategy_name)


def get_strategies_by_domain(domain: str) -> List[str]:
    return [
        name
        for name, info in STRATEGY_REGISTRY.items()
        if info["domain"] == domain or info["domain"] == StrategyDomain.ALL
    ]


def get_strategies_by_category(category: str) -> List[str]:
    return [
        name
        for name, info in STRATEGY_REGISTRY.items()
        if info["category"] == category
    ]
