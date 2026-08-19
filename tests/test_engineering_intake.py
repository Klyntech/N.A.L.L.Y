"""Tests for engineering intake parsing and the build-request classifier."""

from __future__ import annotations

import pytest

from nally.engineering.intake import (
    detect_language_hint,
    extract_constraints,
    is_ambiguous,
    is_full_build_request,
    parse_assumptions,
    parse_task,
)
from nally.engineering.models import EngineeringError


def test_parse_task_basic():
    spec = parse_task("Build a small python CLI tool that organizes files by extension")
    assert "organizes files" in spec.goal
    assert spec.language_hint == "python"
    assert spec.scope == "single_project"


def test_parse_task_no_explicit_language():
    spec = parse_task("Build a small CLI tool that organizes files by extension")
    assert spec.language_hint is None
    assert spec.goal


def test_parse_task_empty_raises():
    with pytest.raises(EngineeringError):
        parse_task("   ")


def test_language_hint_javascript():
    assert detect_language_hint("Create a node.js web app") == "javascript"
    assert detect_language_hint("Write a typescript service") == "typescript"
    assert detect_language_hint("Make a go CLI") == "go"


def test_extract_constraints():
    constraints = extract_constraints(
        "Build a tool with no external dependencies and it must be a single file"
    )
    assert any("no external dependencies" in c for c in constraints)
    assert any("single file" in c for c in constraints)


def test_is_full_build_request_positive():
    assert is_full_build_request("Build a CLI tool that organizes files by extension")
    assert is_full_build_request("Create a web app for tracking tasks")
    assert is_full_build_request("Scaffold a python library for parsing logs")


def test_is_full_build_request_negative():
    assert not is_full_build_request("Explain how recursion works")
    assert not is_full_build_request("Debug this snippet")
    assert not is_full_build_request("Write a small function to add two numbers")
    assert not is_full_build_request("What is the weather in Lagos")


def test_parse_assumptions_json():
    text = '{"assumptions": ["Use Python 3.11", "Single file"], "questions": ["ok?"]}'
    out = parse_assumptions(text)
    assert [a.statement for a in out] == ["Use Python 3.11", "Single file"]


def test_parse_assumptions_bullets():
    text = "- Assume Python 3.11\n- Keep it dependency-free\n- Use stdlib only"
    out = parse_assumptions(text)
    assert len(out) == 3
    assert all(a.resolved for a in out)


def test_is_ambiguous_short_no_hint():
    spec = parse_task("make a thing")
    assert is_ambiguous(spec) is True


def test_is_ambiguous_with_hint():
    spec = parse_task("Build a python CLI tool")
    assert is_ambiguous(spec) is False
