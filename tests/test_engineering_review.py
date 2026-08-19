"""Tests for the static self-critique / review logic."""

from __future__ import annotations

from nally.engineering.models import CritiqueSeverity
from nally.engineering.review import (
    review_codebase,
    review_directory,
    summarize_findings,
)


def test_detects_hardcoded_secret():
    files = {"config.py": 'API_KEY = "sk-1234567890abcdef1234567890ab"\n'}
    findings = review_codebase(files)
    assert any(f.category.value == "security" and f.severity == CritiqueSeverity.HIGH for f in findings)


def test_detects_bare_except():
    files = {"x.py": "def f():\n    try:\n        pass\n    except:\n        pass\n"}
    findings = review_codebase(files)
    assert any(f.category.value == "error_handling" and f.severity == CritiqueSeverity.HIGH for f in findings)


def test_flags_missing_tests():
    files = {"main.py": "def main():\n    return 1\n\nmain()\n"}
    findings = review_codebase(files)
    assert any(f.category.value == "maintainability" and f.severity == CritiqueSeverity.HIGH for f in findings)


def test_clean_code_has_no_high_findings():
    files = {
        "main.py": (
            "def run():\n"
            "    try:\n"
            "        return 1\n"
            "    except ValueError as exc:\n"
            "        raise RuntimeError('bad') from exc\n"
            "\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n\n"  # pad to >=20 lines
        ),
        "test_main.py": "def test_run():\n    assert run() == 1\n",
    }
    findings = review_codebase(files)
    assert not any(f.severity == CritiqueSeverity.HIGH for f in findings)


def test_summarize_needs_refinement():
    files = {"x.py": 'password = "hunter2hunter2hunter2"\n'}
    findings = review_codebase(files)
    report = summarize_findings(findings)
    assert report.needs_refinement is True
    assert report.high_count >= 1
    assert "security" in report.summary.lower() or report.summary


def test_review_directory(tmp_path):
    p = tmp_path / "code.py"
    p.write_text('SECRET_TOKEN = "abcdefghijklmnopqrstuvwxyz1234"\n')
    findings = review_directory(str(tmp_path))
    assert any(f.category.value == "security" for f in findings)
