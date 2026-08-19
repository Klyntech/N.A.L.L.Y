"""Data models for the Nally autonomous engineering subsystem.

All structures are plain dataclasses so they are trivially serializable to the
run manifest and easy to unit-test without any LLM or filesystem access.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Dict, List, Optional


class EngineeringError(Exception):
    """Raised when the engineering loop cannot proceed (bad input, missing
    backend/tool, unrecoverable parse failure, etc.)."""


class ApproachCategory(StrEnum):
    """The three design families the loop must always consider."""

    SIMPLE = "simple"
    ROBUST = "robust_scalable"
    CREATIVE = "creative_unconventional"


class EngineeringStage(StrEnum):
    """Stages of the closed-loop pipeline. Persisted to the run manifest."""

    INTAKE = "intake"
    CLARIFY = "clarify"
    BRAINSTORM = "brainstorm"
    SCORE = "score"
    SELECT = "select"
    DESIGN = "design"
    TESTPLAN = "test_plan"
    IMPLEMENT = "implement"
    TEST = "test"
    CRITIQUE = "critique"
    REFINE = "refine"
    FINALIZE = "finalize"
    DONE = "done"


@dataclass
class Assumption:
    """A single assumption documented during the clarify stage."""

    statement: str
    resolved: bool = True
    auto: bool = True  # True if the agent inferred it, False if user-confirmed

    def to_dict(self) -> Dict[str, Any]:
        return {
            "statement": self.statement,
            "resolved": self.resolved,
            "auto": self.auto,
        }


@dataclass
class TaskSpec:
    """Normalized, parsed form of the raw user task."""

    raw: str
    goal: str
    constraints: List[str] = field(default_factory=list)
    language_hint: Optional[str] = None
    assumptions: List[Assumption] = field(default_factory=list)
    scope: str = "single_project"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "raw": self.raw,
            "goal": self.goal,
            "constraints": list(self.constraints),
            "language_hint": self.language_hint,
            "assumptions": [a.to_dict() for a in self.assumptions],
            "scope": self.scope,
        }


@dataclass
class Approach:
    """A single solution design proposed during brainstorming."""

    id: str
    title: str
    category: ApproachCategory
    summary: str
    description: str = ""
    pros: List[str] = field(default_factory=list)
    cons: List[str] = field(default_factory=list)
    risks: List[str] = field(default_factory=list)
    technologies: List[str] = field(default_factory=list)
    # Optional 1..5 axis scores, populated when the brainstorm LLM returns them.
    feasibility: Optional[float] = None
    simplicity: Optional[float] = None
    maintainability: Optional[float] = None
    performance: Optional[float] = None
    novelty: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "category": self.category.value,
            "summary": self.summary,
            "description": self.description,
            "pros": list(self.pros),
            "cons": list(self.cons),
            "risks": list(self.risks),
            "technologies": list(self.technologies),
            "scores": {
                "feasibility": self.feasibility,
                "simplicity": self.simplicity,
                "maintainability": self.maintainability,
                "performance": self.performance,
                "novelty": self.novelty,
            },
        }


@dataclass
class ApproachScore:
    """Numeric evaluation of an Approach across the five required axes."""

    approach_id: str
    feasibility: float
    simplicity: float
    maintainability: float
    performance: float
    novelty: float
    rationale: str = ""
    weighted_total: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "approach_id": self.approach_id,
            "feasibility": self.feasibility,
            "simplicity": self.simplicity,
            "maintainability": self.maintainability,
            "performance": self.performance,
            "novelty": self.novelty,
            "rationale": self.rationale,
            "weighted_total": round(self.weighted_total, 4),
        }


@dataclass
class FilePlan:
    """One planned source file."""

    path: str
    purpose: str
    language: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "purpose": self.purpose,
            "language": self.language,
            "dependencies": list(self.dependencies),
        }


@dataclass
class DesignPlan:
    """Architecture + file plan produced after approach selection."""

    goal: str
    architecture_summary: str = ""
    components: List[Dict[str, Any]] = field(default_factory=list)
    data_flow: str = ""
    file_plan: List[FilePlan] = field(default_factory=list)
    tech_stack: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "goal": self.goal,
            "architecture_summary": self.architecture_summary,
            "components": list(self.components),
            "data_flow": self.data_flow,
            "file_plan": [f.to_dict() for f in self.file_plan],
            "tech_stack": list(self.tech_stack),
            "dependencies": list(self.dependencies),
        }


@dataclass
class TestCase:
    """A single planned test."""

    name: str
    description: str
    target: str = ""
    kind: str = "unit"
    expected: str = "pass"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "target": self.target,
            "kind": self.kind,
            "expected": self.expected,
        }


@dataclass
class TestPlan:
    """The test strategy produced before implementation."""

    framework: str
    cases: List[TestCase] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "framework": self.framework,
            "cases": [c.to_dict() for c in self.cases],
        }


class CritiqueSeverity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class CritiqueCategory(StrEnum):
    EDGE_CASE = "edge_case"
    ERROR_HANDLING = "error_handling"
    SECURITY = "security"
    READABILITY = "readability"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"


@dataclass
class CritiqueFinding:
    """A single self-review observation."""

    category: CritiqueCategory
    severity: CritiqueSeverity
    message: str
    location: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category.value,
            "severity": self.severity.value,
            "message": self.message,
            "location": self.location,
        }


@dataclass
class CritiqueReport:
    """Aggregated result of the self-critique stage."""

    findings: List[CritiqueFinding] = field(default_factory=list)
    summary: str = ""
    needs_refinement: bool = False

    @property
    def high_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == CritiqueSeverity.HIGH)

    @property
    def medium_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == CritiqueSeverity.MEDIUM)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "findings": [f.to_dict() for f in self.findings],
            "summary": self.summary,
            "needs_refinement": self.needs_refinement,
            "high_count": self.high_count,
            "medium_count": self.medium_count,
        }


@dataclass
class EngineeringResult:
    """Final deliverable returned by the loop."""

    task: str
    chosen_approach: Optional[Approach]
    scorecard: List[ApproachScore]
    design: Optional[DesignPlan]
    test_plan: Optional[TestPlan]
    artifacts: List[str] = field(default_factory=list)
    readme_path: str = ""
    manifest_path: str = ""
    scorecard_path: str = ""
    dependencies: List[str] = field(default_factory=list)
    run_commands: List[str] = field(default_factory=list)
    known_limitations: List[str] = field(default_factory=list)
    refinements: int = 0
    success: bool = False
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task": self.task,
            "chosen_approach": self.chosen_approach.to_dict() if self.chosen_approach else None,
            "scorecard": [s.to_dict() for s in self.scorecard],
            "design": self.design.to_dict() if self.design else None,
            "test_plan": self.test_plan.to_dict() if self.test_plan else None,
            "artifacts": list(self.artifacts),
            "readme_path": self.readme_path,
            "manifest_path": self.manifest_path,
            "scorecard_path": self.scorecard_path,
            "dependencies": list(self.dependencies),
            "run_commands": list(self.run_commands),
            "known_limitations": list(self.known_limitations),
            "refinements": self.refinements,
            "success": self.success,
            "notes": list(self.notes),
        }
