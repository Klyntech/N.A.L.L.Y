"""Prompt templates for every LLM stage of the engineering loop.

Prompts deliberately embed the required creativity mechanisms: multi-path
brainstorming, design tradeoff analysis, analogy-based thinking, constraint
inversion, alternative architecture generation, and self-critique. Keeping them
here makes the loop logic readable and the prompts easy to tune.
"""

from __future__ import annotations

from typing import List

from .models import Approach, TaskSpec, TestPlan

_BRAINSTORM_TECHNIQUES = (
    "Use multiple creativity mechanisms:\n"
    "- Multi-path brainstorming: produce genuinely different designs, not variants.\n"
    "- Analogy-based thinking: liken the problem to a well-known system and borrow its shape.\n"
    "- Constraint inversion: ask 'what if the opposite constraint held?' to surface novel designs.\n"
    "- Alternative architecture generation: consider at least one unconventional structure.\n"
)


def intake_prompt(raw_task: str) -> str:
    return (
        "You are the intake stage of an autonomous software engineering agent.\n"
        "Given the user's raw request, list concise clarifying questions (max 3) and the\n"
        "assumptions you will make if the user does not answer. Respond ONLY with JSON:\n"
        '{"assumptions": ["..."], "questions": ["..."], "needs_clarification": true/false}\n'
        f"\nUSER REQUEST:\n{raw_task}"
    )


def clarify_system() -> str:
    return (
        "You convert a software task into explicit, documented assumptions. "
        "Be concise and pragmatic; prefer sensible defaults over asking."
    )


def brainstorm_system() -> str:
    return (
        "You are a creative principal engineer. Generate solution approaches for a task.\n"
        "You MUST return exactly the JSON schema below with at least THREE approaches, one per\n"
        "category (simple, robust_scalable, creative_unconventional). Score each 1..5 on:\n"
        "feasibility, simplicity, maintainability, performance, novelty.\n"
        + _BRAINSTORM_TECHNIQUES
        + "\nRESPOND ONLY WITH JSON:\n"
        '{"approaches": [{"id":"a1","title":"...","category":"simple",'
        '"summary":"...","description":"...","pros":[...],"cons":[...],"risks":[...],'
        '"technologies":[...],'
        '"scores":{"feasibility":4,"simplicity":5,"maintainability":4,"performance":3,"novelty":2}}, ... ]}'
    )


def brainstorm_prompt(spec: TaskSpec) -> str:
    constraints = "; ".join(spec.constraints) if spec.constraints else "none stated"
    lang = spec.language_hint or "unspecified"
    return (
        f"TASK: {spec.goal}\n"
        f"TARGET LANGUAGE: {lang}\n"
        f"CONSTRAINTS: {constraints}\n\n"
        "Produce three clearly distinct approaches as specified."
    )


def design_system() -> str:
    return (
        "You are a software architect. Given a chosen approach, produce a concrete design.\n"
        "Respond ONLY with JSON:\n"
        '{"goal":"...","architecture_summary":"...","components":[{"name":"...","responsibility":"..."}],'
        '"data_flow":"...","tech_stack":["..."],"dependencies":["..."],'
        '"file_plan":[{"path":"...","purpose":"...","language":"...","dependencies":["..."]}]}'
    )


def design_prompt(spec: TaskSpec, chosen: Approach) -> str:
    return (
        f"TASK: {spec.goal}\n"
        f"CHOSEN APPROACH: {chosen.title} ({chosen.category.value})\n"
        f"SUMMARY: {chosen.summary}\n"
        f"TECHNOLOGIES: {', '.join(chosen.technologies) or 'your discretion'}\n\n"
        "Design the architecture and list every file needed."
    )


def test_plan_system() -> str:
    return (
        "You write test plans. Respond ONLY with JSON:\n"
        '{"framework":"pytest","cases":[{"name":"...","description":"...","target":"...",'
        '"kind":"unit","expected":"pass"}]}'
    )


def test_plan_prompt(spec: TaskSpec, design_plan) -> str:
    files = ", ".join(f.path for f in design_plan.file_plan) or "the implementation files"
    return (
        f"TASK: {spec.goal}\n"
        f"FILES TO TEST: {files}\n\n"
        "Write a focused test plan covering happy path, edge cases, and error handling."
    )


def implement_system() -> str:
    return (
        "You implement software. Respond ONLY with JSON mapping each file path to its full content:\n"
        '{"files":[{"path":"main.py","content":"..."}]}\n'
        "Write COMPLETE, working files. No placeholders, no TODO stubs, no truncation. "
        "Do not include emojis. Handle errors and edge cases."
    )


def implement_prompt(spec: TaskSpec, design_plan, test_plan: TestPlan, mode: str = "initial") -> str:
    files_block = "\n".join(
        f"- {f.path}: {f.purpose}" for f in design_plan.file_plan
    )
    tests_block = "\n".join(f"- {c.name}: {c.description}" for c in test_plan.cases) or "(none)"
    extra = ""
    if mode == "refine":
        extra = (
            "\n\nThis is a REFINEMENT pass. Fix the issues described below while preserving "
            "working behavior. Return ALL files (not just the changed ones)."
        )
    return (
        f"TASK: {spec.goal}\n"
        f"MODE: {mode}\n\n"
        f"FILE PLAN:\n{files_block}\n\n"
        f"TEST PLAN:\n{tests_block}\n"
        f"{extra}"
    )


def critique_system() -> str:
    return (
        "You are a rigorous code reviewer. Given the implementation and test results, "
        "list concrete defects and improvements across: edge cases, error handling, "
        "security, readability, performance, maintainability. Respond ONLY with JSON:\n"
        '{"summary":"...","findings":[{"category":"security","severity":"high","message":"..."}]}'
    )


def critique_prompt(
    spec: TaskSpec,
    design_plan,
    test_output: str,
    test_passed: bool,
    static_findings: str,
) -> str:
    return (
        f"TASK: {spec.goal}\n"
        f"TESTS PASSED: {test_passed}\n"
        f"TEST OUTPUT (last 3000 chars):\n{test_output[-3000:]}\n\n"
        f"STATIC REVIEW FINDINGS:\n{static_findings or 'none'}\n\n"
        "Critique the implementation. If tests failed, prioritize the failures."
    )


def finalize_prompt(spec: TaskSpec, design_plan, result_summary: str) -> str:
    return (
        f"TASK: {spec.goal}\n"
        f"RESULT SUMMARY: {result_summary}\n\n"
        "List known limitations of the delivered solution (max 6, concise bullets). "
        "Respond ONLY with JSON: {\"known_limitations\": [\"...\"]}"
    )
