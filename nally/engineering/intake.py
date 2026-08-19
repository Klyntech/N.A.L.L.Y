"""Task intake: parse the raw request and decide if it is a full build task.

All functions here are pure (no LLM, no filesystem) so they are trivially
unit-testable. The classifier is used by the `build` skill to decide whether to
route a request into the engineering loop.
"""

from __future__ import annotations

import re
from typing import List, Optional

from ._json import extract_json
from .models import Assumption, EngineeringError, TaskSpec

_LANG_PATTERNS = {
    "python": [r"\bpython\b", r"\b\.py\b", r"\bpy\b"],
    "javascript": [r"\bjavascript\b", r"\bnode\.?js\b", r"\bnode\b", r"\b\.js\b"],
    "typescript": [r"\btypescript\b", r"\b\.ts\b", r"\bts\b"],
    "go": [r"\bgolang\b", r"\bgo lang\b", r"\b\.go\b", r"\bgo (?:cli|app|program|lang|service|tool|api|module)\b"],
    "rust": [r"\brust\b", r"\b\.rs\b"],
    "java": [r"\bjava\b", r"\b\.java\b"],
    "csharp": [r"\bc#\b", r"\b\.cs\b", r"\bcsharp\b"],
    "ruby": [r"\bruby\b", r"\b\.rb\b"],
    "php": [r"\bphp\b", r"\b\.php\b"],
}

_CONSTRAINT_PATTERNS = [
    r"without\s+(?:using\s+)?(?:any\s+)?(?:external\s+)?(?:libraries|dependencies|packages|frameworks)",
    r"no\s+(?:external\s+)?(?:dependencies|libraries|packages|frameworks)",
    r"single[- ]file",
    r"in\s+a\s+single\s+file",
    r"using\s+only\s+([^\.]+)",
    r"must\s+(?:be|support|handle)\s+([^\.]+)",
    r"should\s+(?:be|support|handle)\s+([^\.]+)",
    r"only\s+use\s+([^\.]+)",
    r"no\s+(?:api\s+key|network|internet|external\s+service)",
]

_FULL_BUILD_PATTERNS = [
    r"\bbuild\b",
    r"\bcreate\b",
    r"\bscaffold\b",
    r"\bgenerate\b",
    r"\bimplement\b",
    r"\bmake\b",
    r"\bdevelop\b",
    r"\bset\s+up\b",
    r"\bwrite\b",
]

_FULL_BUILD_OBJECTS = [
    r"\bproject\b",
    r"\bsystem\b",
    r"\bapp\b",
    r"\bapplication\b",
    r"\bcli\b",
    r"\btool\b",
    r"\bpackage\b",
    r"\blibrary\b",
    r"\bapi\b",
    r"\bservice\b",
    r"\bwebsite\b",
    r"\bweb\s*app\b",
    r"\bbot\b",
    r"\bdaemon\b",
    r"\bmodule\b",
]


def detect_language_hint(text: str) -> Optional[str]:
    """Best-effort detection of the target language from free text."""
    lowered = text.lower()
    for lang, patterns in _LANG_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, lowered):
                return lang
    return None


def extract_constraints(text: str) -> List[str]:
    """Pull out constraint-like clauses from the task text."""
    constraints: List[str] = []
    for pat in _CONSTRAINT_PATTERNS:
        for m in re.finditer(pat, text, re.IGNORECASE):
            clause = m.group(0).strip()
            if clause and clause not in constraints:
                constraints.append(clause)
    return constraints


def parse_task(raw: str, assumptions: Optional[List[Assumption]] = None) -> TaskSpec:
    """Parse a raw task string into a normalized :class:`TaskSpec`."""
    if not raw or not raw.strip():
        raise EngineeringError("Empty task cannot be parsed")

    raw = raw.strip()
    # The goal is the raw text, lightly cleaned of trailing punctuation/quotes.
    goal = raw.strip().strip('"').strip("'").rstrip(".")
    language_hint = detect_language_hint(goal)
    constraints = extract_constraints(goal)

    return TaskSpec(
        raw=raw,
        goal=goal,
        constraints=constraints,
        language_hint=language_hint,
        assumptions=list(assumptions or []),
        scope="single_project",
    )


def is_full_build_request(text: str) -> bool:
    """Heuristic: does this look like a request for a full project build?

    Triggers on build/create/scaffold intent combined with a project-like
    object noun. Small asks (snippets, explanations, bug fixes) do NOT match.
    """
    lowered = (text or "").lower()
    if not lowered.strip():
        return False

    has_build_verb = any(re.search(p, lowered) for p in _FULL_BUILD_PATTERNS)
    has_object = any(re.search(p, lowered) for p in _FULL_BUILD_OBJECTS)
    if not (has_build_verb and has_object):
        return False

    # Exclusions: these are not "build me a whole project" intents.
    exclusions = [
        r"\b(explain|what is|how (do|to)|why|debug|fix|refactor this|review this|tell me about)\b",
        r"\bsnippet\b",
        r"\bexample\b",
        r"\bone[- ]line\b",
        r"\bsmall (function|script|piece)\b",
    ]
    if any(re.search(p, lowered) for p in exclusions):
        return False
    return True


def parse_assumptions(text: str) -> List[Assumption]:
    """Parse an LLM-produced assumptions block into structured assumptions.

    Accepts either a JSON list/object with an ``assumptions`` key, or a plain
    bullet/numbered list. Falls back to a single catch-all assumption.
    """
    text = (text or "").strip()
    if not text:
        return []

    # Try JSON first.
    try:
        data = extract_json(text)
        items = None
        if isinstance(data, dict):
            items = data.get("assumptions") or data.get("questions")
        elif isinstance(data, list):
            items = data
        if items:
            out: List[Assumption] = []
            for it in items:
                if isinstance(it, str):
                    out.append(Assumption(statement=it.strip(), resolved=True, auto=True))
                elif isinstance(it, dict):
                    stmt = it.get("statement") or it.get("assumption") or it.get("text") or ""
                    if stmt:
                        out.append(Assumption(statement=str(stmt).strip(), resolved=True, auto=True))
            if out:
                return out
    except EngineeringError:
        pass

    # Fall back to line parsing for "- " or "1." bullet lists.
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        cleaned = re.sub(r"^[-*]\s+", "", line)
        cleaned = re.sub(r"^\d+[.)]\s+", "", cleaned)
        cleaned = cleaned.strip().strip('"').strip("'")
        if cleaned and len(cleaned) > 3:
            out.append(Assumption(statement=cleaned, resolved=True, auto=True))
    return out[:20]


def is_ambiguous(spec: TaskSpec) -> bool:
    """Decide whether a clarification question is warranted.

    A task is considered ambiguous (and worth one confirmation question) if it
    lacks both a language hint and any concrete constraints to bound scope.
    """
    if spec.language_hint:
        return False
    if spec.constraints:
        return False
    vague_words = ["something", "anything", "a thing", "whatever", "some app"]
    lowered = spec.goal.lower()
    if any(w in lowered for w in vague_words):
        return True
    # Very short, object-free goals are ambiguous.
    return len(spec.goal.split()) < 4
