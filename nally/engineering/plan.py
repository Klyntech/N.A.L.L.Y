"""Parsing of design plans, file plans, and test plans from LLM JSON.

Pure functions: no LLM, no filesystem. Robust to partial or messy output.
"""

from __future__ import annotations

from typing import Any, Dict, List

from ._json import extract_json
from .models import (
    DesignPlan,
    EngineeringError,
    FilePlan,
    TestCase,
    TestPlan,
)


def parse_design_plan(text: str, goal: str = "") -> DesignPlan:
    """Parse an LLM response into a :class:`DesignPlan`."""
    if not text or not text.strip():
        raise EngineeringError("Empty design plan response")

    data = extract_json(text)
    if not isinstance(data, dict):
        raise EngineeringError("Design plan must be a JSON object")

    file_plan = _parse_file_plan(data.get("file_plan") or data.get("files") or [])
    deps = _as_str_list(data.get("dependencies") or data.get("tech_stack"))

    return DesignPlan(
        goal=str(data.get("goal") or goal),
        architecture_summary=str(data.get("architecture_summary") or data.get("summary") or ""),
        components=_as_component_list(data.get("components") or []),
        data_flow=str(data.get("data_flow") or ""),
        file_plan=file_plan,
        tech_stack=_as_str_list(data.get("tech_stack") or data.get("stack")),
        dependencies=deps,
    )


def _parse_file_plan(raw: Any) -> List[FilePlan]:
    out: List[FilePlan] = []
    if not isinstance(raw, list):
        return out
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or item.get("file") or f"file_{i + 1}.txt")
        out.append(
            FilePlan(
                path=path,
                purpose=str(item.get("purpose") or item.get("description") or ""),
                language=str(item.get("language") or "") or None,
                dependencies=_as_str_list(item.get("dependencies")),
            )
        )
    return out


def _as_component_list(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            out.append(item)
        elif isinstance(item, str):
            out.append({"name": item})
    return out


def parse_test_plan(text: str) -> TestPlan:
    """Parse an LLM response into a :class:`TestPlan`."""
    if not text or not text.strip():
        raise EngineeringError("Empty test plan response")

    data = extract_json(text)
    if not isinstance(data, dict):
        raise EngineeringError("Test plan must be a JSON object")

    framework = str(data.get("framework") or _infer_framework(data)).strip() or "pytest"
    cases = _parse_cases(data.get("cases") or data.get("tests") or [])

    # If the LLM gave no explicit cases, synthesize one smoke test per file plan
    # target is not available here; leave empty rather than fabricate.
    return TestPlan(framework=framework, cases=cases)


def _infer_framework(data: Dict[str, Any]) -> str:
    combined = " ".join(str(v) for v in data.values()).lower()
    if "pytest" in combined:
        return "pytest"
    if "unittest" in combined:
        return "unittest"
    if "jest" in combined:
        return "jest"
    if "mocha" in combined:
        return "mocha"
    if "go test" in combined:
        return "go test"
    return "pytest"


def _parse_cases(raw: Any) -> List[TestCase]:
    out: List[TestCase] = []
    if not isinstance(raw, list):
        return out
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("title") or f"test_{i + 1}")
        out.append(
            TestCase(
                name=name,
                description=str(item.get("description") or item.get("what") or ""),
                target=str(item.get("target") or item.get("file") or ""),
                kind=str(item.get("kind") or "unit"),
                expected=str(item.get("expected") or "pass"),
            )
        )
    return out


def parse_implementation(files_json: str) -> Dict[str, str]:
    """Parse an LLM response that returns file contents.

    Accepts either a JSON object mapping path -> content, or an object with a
    ``files`` array of ``{"path": ..., "content": ...}`` entries. Returns a
    dict of ``{path: content}``.
    """
    if not files_json or not files_json.strip():
        raise EngineeringError("Empty implementation response")

    data = extract_json(files_json)
    out: Dict[str, str] = {}

    if isinstance(data, dict):
        if "files" in data and isinstance(data["files"], list):
            for item in data["files"]:
                if isinstance(item, dict) and item.get("path") and "content" in item:
                    out[str(item["path"])] = str(item["content"])
        else:
            # Treat top-level string values as file contents.
            for k, v in data.items():
                if isinstance(v, str) and ("\n" in v or len(v) > 0):
                    out[str(k)] = v

    if not out:
        raise EngineeringError("No files found in implementation response")
    return out


def _as_str_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [v.strip() for v in value.split("\n") if v.strip()]
    if isinstance(value, list):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value)]
