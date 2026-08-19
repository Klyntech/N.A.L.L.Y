"""Tests for design / test-plan / implementation parsing."""

from __future__ import annotations

import pytest

from nally.engineering.models import EngineeringError
from nally.engineering.plan import (
    parse_design_plan,
    parse_implementation,
    parse_test_plan,
)

_DESIGN = """
{
  "goal": "Organize files by extension",
  "architecture_summary": "CLI that groups files in a folder by suffix.",
  "components": [{"name":"cli","responsibility":"entrypoint"}],
  "data_flow": "args -> scan -> group -> print",
  "tech_stack": ["python"],
  "dependencies": [],
  "file_plan": [
    {"path":"main.py","purpose":"entrypoint","language":"python"},
    {"path":"test_main.py","purpose":"tests","language":"python"}
  ]
}
"""

_TEST = """
{
  "framework":"pytest",
  "cases":[
    {"name":"test_groups_files","description":"groups by ext","target":"test_main.py","kind":"unit"},
    {"name":"test_missing_dir","description":"raises on missing","target":"test_main.py","kind":"unit"}
  ]
}
"""


def test_parse_design_plan():
    dp = parse_design_plan(_DESIGN, "Organize files by extension")
    assert dp.goal
    assert len(dp.file_plan) == 2
    assert dp.file_plan[0].path == "main.py"
    assert dp.architecture_summary.startswith("CLI")


def test_parse_design_plan_invalid_raises():
    with pytest.raises(EngineeringError):
        parse_design_plan("just text no json")


def test_parse_test_plan():
    tp = parse_test_plan(_TEST)
    assert tp.framework == "pytest"
    assert len(tp.cases) == 2
    assert tp.cases[0].name == "test_groups_files"


def test_parse_implementation_files_array():
    text = (
        '{"files":['
        '{"path":"main.py","content":"print(1)\\n"},'
        '{"path":"README.md","content":"# hi"}'
        ']}'
    )
    files = parse_implementation(text)
    assert files["main.py"] == "print(1)\n"
    assert files["README.md"] == "# hi"


def test_parse_implementation_object_map():
    text = '{"main.py":"x=1","util.py":"y=2"}'
    files = parse_implementation(text)
    assert set(files.keys()) == {"main.py", "util.py"}


def test_parse_implementation_empty_raises():
    with pytest.raises(EngineeringError):
        parse_implementation("{}")
