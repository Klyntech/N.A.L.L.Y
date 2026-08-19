"""Self-critique: static code review and critique-report assembly.

Provides deterministic, filesystem-independent checks (so they are unit-testable
with an in-memory dict) plus a directory scanner that reads real files. The
LLM-driven critique text is aggregated with the static findings to decide
whether the loop must refine.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List

from .models import (
    CritiqueCategory,
    CritiqueFinding,
    CritiqueReport,
    CritiqueSeverity,
    EngineeringError,
)

# High-severity signals: secrets / credentials accidentally hardcoded.
_SECRET_PATTERNS = [
    re.compile(r"api[_-]?key\s*=\s*['\"][A-Za-z0-9_\-]{12,}['\"]", re.IGNORECASE),
    re.compile(r"secret\s*=\s*['\"][A-Za-z0-9_\-]{12,}['\"]", re.IGNORECASE),
    re.compile(r"password\s*=\s*['\"][^\s'\"]{6,}['\"]", re.IGNORECASE),
    re.compile(r"token\s*=\s*['\"][A-Za-z0-9_\-\.]{12,}['\"]", re.IGNORECASE),
    re.compile(r"sk-[A-Za-z0-9]{20,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-\.]{20,}"),
]

_BARE_EXCEPT = re.compile(r"except\s*:")
_LONG_LINE = 120
_MAX_FILE_LINES = 800


def review_codebase(file_contents: Dict[str, str]) -> List[CritiqueFinding]:
    """Run static self-review over an in-memory ``{path: content}`` map."""
    findings: List[CritiqueFinding] = []
    code_files = {
        p: c for p, c in file_contents.items() if _looks_like_code(p)
    }

    for path, content in code_files.items():
        findings.extend(_review_one_file(path, content))

    # Cross-file: missing tests when code exists.
    has_code = bool(code_files)
    has_tests = any(_looks_like_test(p) for p in file_contents)
    if has_code and not has_tests:
        findings.append(
            CritiqueFinding(
                category=CritiqueCategory.MAINTAINABILITY,
                severity=CritiqueSeverity.HIGH,
                message="No test files detected in the generated project.",
                location="",
            )
        )
    return findings


def _review_one_file(path: str, content: str) -> List[CritiqueFinding]:
    findings: List[CritiqueFinding] = []

    # Security: hardcoded secrets.
    for pat in _SECRET_PATTERNS:
        for m in pat.finditer(content):
            findings.append(
                CritiqueFinding(
                    category=CritiqueCategory.SECURITY,
                    severity=CritiqueSeverity.HIGH,
                    message=f"Possible hardcoded secret: {m.group(0)[:24]}...",
                    location=path,
                )
            )

    # Reliability: bare `except:`.
    if re.search(r"except\s*:", content):
        findings.append(
            CritiqueFinding(
                category=CritiqueCategory.ERROR_HANDLING,
                severity=CritiqueSeverity.HIGH,
                message="Bare 'except:' swallows all errors; catch specific exceptions.",
                location=path,
            )
        )

    # Error handling: non-trivial file with no try/raise/except at all.
    if _is_non_trivial(content):
        if not re.search(r"\btry\b|\braise\b|\bexcept\b", content):
            findings.append(
                CritiqueFinding(
                    category=CritiqueCategory.ERROR_HANDLING,
                    severity=CritiqueSeverity.MEDIUM,
                    message="No error handling (no try/raise/except) in a non-trivial module.",
                    location=path,
                )
            )

    # Readability: over-long lines.
    for i, line in enumerate(content.splitlines(), 1):
        if len(line) > _LONG_LINE:
            findings.append(
                CritiqueFinding(
                    category=CritiqueCategory.READABILITY,
                    severity=CritiqueSeverity.LOW,
                    message=f"Line {i} is {len(line)} chars (> {_LONG_LINE}).",
                    location=path,
                )
            )
            break  # one note per file is enough

    # Maintainability: very large file.
    if content.count("\n") > _MAX_FILE_LINES:
        findings.append(
            CritiqueFinding(
                category=CritiqueCategory.MAINTAINABILITY,
                severity=CritiqueSeverity.LOW,
                message=f"File is {content.count(chr(10))} lines (> {_MAX_FILE_LINES}); consider splitting.",
                location=path,
            )
        )
    return findings


def review_directory(path: str) -> List[CritiqueFinding]:
    """Scan a real directory and run :func:`review_codebase` on its files."""
    root = Path(path)
    if not root.exists():
        raise EngineeringError(f"Workspace path does not exist: {path}")
    contents: Dict[str, str] = {}
    try:
        for f in root.rglob("*"):
            if f.is_file() and not _is_skippable(f):
                try:
                    contents[str(f)] = f.read_text(encoding="utf-8")
                except (UnicodeDecodeError, PermissionError, OSError):
                    continue
    except Exception as exc:
        raise EngineeringError(f"Failed reading workspace: {exc}") from exc
    return review_codebase(contents)


def summarize_findings(
    findings: List[CritiqueFinding],
    llm_critique: str = "",
) -> CritiqueReport:
    """Combine static findings (+ optional LLM critique text) into a report."""
    high = sum(1 for f in findings if f.severity == CritiqueSeverity.HIGH)
    medium = sum(1 for f in findings if f.severity == CritiqueSeverity.MEDIUM)
    # Needs refinement if any high-severity issue, or >2 medium issues.
    needs = high > 0 or medium > 2
    summary = llm_critique.strip()
    if not summary:
        if not findings:
            summary = "Static review found no issues."
        else:
            summary = (
                f"{high} high / {medium} medium issues found across "
                f"{len(findings)} checks."
            )
    return CritiqueReport(findings=findings, summary=summary, needs_refinement=needs)


def _looks_like_code(path: str) -> bool:
    return path.lower().endswith(
        (".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs", ".java", ".cs", ".rb", ".php", ".c", ".cpp", ".h")
    )


def _looks_like_test(path: str) -> bool:
    p = path.lower()
    return "test" in Path(p).name or "test" in Path(p).parent.name or p.endswith("_test.py")


def _is_skippable(path: Path) -> bool:
    parts = set(path.parts)
    return bool(parts & {"__pycache__", ".git", "node_modules", "data", "logs"})


def _is_non_trivial(content: str) -> bool:
    # Heuristic: has a function/class definition and more than ~20 lines.
    if not re.search(r"\b(def|class|function|func)\b", content):
        return False
    return content.count("\n") >= 20
