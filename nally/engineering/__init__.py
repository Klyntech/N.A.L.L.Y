"""Nally autonomous engineering subsystem.

Public API for the closed-loop software engineering pipeline. Import nothing
heavy here so the package is safe to import anywhere (tests, CLI, skill).
"""

from __future__ import annotations

from typing import Any, Dict

from .loop import EngineeringLoop
from .models import (
    Approach,
    ApproachScore,
    CritiqueReport,
    DesignPlan,
    EngineeringError,
    EngineeringResult,
    EngineeringStage,
    TaskSpec,
    TestPlan,
)
from .protocol import FakeLLMBackend, LLMBackend, NallyLLMBackend
from .toolbox import FakeToolbox, RealToolbox, Toolbox
from .workspace import EngineeringWorkspace

__all__ = [
    "EngineeringLoop",
    "EngineeringError",
    "EngineeringResult",
    "EngineeringStage",
    "TaskSpec",
    "Approach",
    "ApproachScore",
    "DesignPlan",
    "TestPlan",
    "CritiqueReport",
    "LLMBackend",
    "NallyLLMBackend",
    "FakeLLMBackend",
    "Toolbox",
    "RealToolbox",
    "FakeToolbox",
    "EngineeringWorkspace",
    "run_engineering",
]


def run_engineering(
    task: str,
    *,
    backend: object = None,
    toolbox: object = None,
    workspace: EngineeringWorkspace = None,
    max_refinements: int = 3,
    verbose: bool = False,
    emit: object = None,
    **kwargs,
) -> EngineeringResult:
    """Convenience constructor: build a loop and run it.

    If ``backend``/``toolbox``/``workspace`` are omitted, real implementations
    are used (Nally LLM backend, real gated toolbox, default workspace). For
    tests, pass ``FakeLLMBackend`` / ``FakeToolbox`` and a temp workspace.

    When ``verbose`` is True (and no custom ``emit`` is supplied), a progress
    printer is installed so the CLI shows live stage transitions instead of
    appearing to hang.
    """
    if workspace is None:
        workspace = EngineeringWorkspace(task=task)
    if backend is None:
        backend = NallyLLMBackend()
    if toolbox is None:
        toolbox = RealToolbox()
    if emit is None and verbose:
        emit = _cli_emit
    loop = EngineeringLoop(
        backend, toolbox, workspace, max_refinements=max_refinements, emit=emit, **kwargs
    )
    return loop.run(task)


def _cli_emit(stage: str, data: Dict[str, Any]) -> None:
    """Lightweight progress printer for CLI use."""
    msg = stage
    if isinstance(data, dict):
        parts = []
        for key in ("goal", "chosen_id", "count", "framework", "passed",
                    "files", "iteration", "success", "attempt", "error"):
            if key in data and data[key] is not None:
                val = data[key]
                if isinstance(val, list):
                    val = f"{len(val)} items"
                parts.append(f"{key}={val}")
        if parts:
            msg += " (" + ", ".join(parts[:6]) + ")"
    print(f"[engineering] {msg}", flush=True)
