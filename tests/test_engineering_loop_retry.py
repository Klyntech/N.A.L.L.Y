"""Tests that the implement stage retries on an empty LLM response.

This directly reproduces the live failure: the real backend raised
``EngineeringError("LLM returned empty response")`` at the implement stage
because the default 4096-token cap truncated a large multi-file payload. The
loop must now recover via its own retry, and the real backend additionally
retries empty responses with a larger token budget.
"""

from __future__ import annotations

import json

from nally.engineering import run_engineering
from nally.engineering.protocol import FakeLLMBackend
from nally.engineering.toolbox import FakeToolbox
from nally.engineering.workspace import EngineeringWorkspace

MAIN_OK = (
    "def organize_by_extension(folder):\n"
    "    return {}\n"
)
TEST_OK = (
    "def test_x():\n"
    "    assert organize_by_extension('x') == {}\n"
)


def _brainstorm():
    return json.dumps(
        {
            "approaches": [
                {
                    "id": "a1",
                    "title": "Naive script",
                    "category": "simple",
                    "summary": "One file, stdlib only",
                    "pros": ["simple"],
                    "cons": ["limited"],
                    "scores": {"feasibility": 5, "simplicity": 5, "maintainability": 3, "performance": 3, "novelty": 2},
                },
                {
                    "id": "a2",
                    "title": "Layered app",
                    "category": "robust_scalable",
                    "summary": "Structured, tested",
                    "pros": ["solid"],
                    "cons": ["more code"],
                    "scores": {"feasibility": 5, "simplicity": 3, "maintainability": 5, "performance": 4, "novelty": 3},
                },
                {
                    "id": "a3",
                    "title": "Streaming pipeline",
                    "category": "creative_unconventional",
                    "summary": "Treat files as a stream",
                    "pros": ["novel"],
                    "cons": ["risky"],
                    "scores": {"feasibility": 3, "simplicity": 2, "maintainability": 3, "performance": 5, "novelty": 5},
                },
            ]
        }
    )


def _design():
    return json.dumps(
        {
            "goal": "organize",
            "architecture_summary": "cli",
            "components": [],
            "data_flow": "x",
            "tech_stack": ["python"],
            "dependencies": [],
            "file_plan": [
                {"path": "main.py", "purpose": "x", "language": "python"},
                {"path": "test_main.py", "purpose": "t", "language": "python"},
            ],
        }
    )


def _test_plan():
    return json.dumps(
        {
            "framework": "pytest",
            "cases": [{"name": "test_x", "description": "d", "target": "test_main.py"}],
        }
    )


def _implement(main, test):
    return json.dumps(
        {
            "files": [
                {"path": "main.py", "content": main},
                {"path": "test_main.py", "content": test},
            ]
        }
    )


def _finalize():
    return json.dumps({"known_limitations": []})


def _responses(initial_main):
    return {
        "clarify": json.dumps({"assumptions": ["Use Python"], "questions": [], "needs_clarification": False}),
        "brainstorm": _brainstorm(),
        "design": _design(),
        "test_plan": _test_plan(),
        "implement": _implement(initial_main, TEST_OK),
        "finalize": _finalize(),
    }


def test_loop_retries_empty_implement(tmp_path):
    responses = _responses(MAIN_OK)
    # First implement call returns empty (simulates the live "empty response"
    # bug); the loop must recover on the second attempt.
    responses["implement"] = ["", _implement(MAIN_OK, TEST_OK)]
    backend = FakeLLMBackend(responses, default="{}")
    toolbox = FakeToolbox(test_result=("1 passed", True), lint_result=("", True))
    ws = EngineeringWorkspace(base_dir=tmp_path, task="organize files")
    result = run_engineering(
        "Build a CLI tool that organizes files by extension",
        backend=backend,
        toolbox=toolbox,
        workspace=ws,
    )

    assert result.success is True
    # Exactly one retry happened: the loop made two implement calls total
    # (one empty, one valid) before proceeding.
    implement_calls = [c for c in backend.calls if c["stage"] == "implement"]
    assert len(implement_calls) == 2
