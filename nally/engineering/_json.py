"""Robust JSON extraction for LLM outputs.

LLM responses frequently wrap JSON in markdown fences or add prose. This helper
pulls out the first balanced JSON object or array regardless of surrounding text.
"""

from __future__ import annotations

import json
from typing import Any

from .models import EngineeringError


def extract_json(text: str) -> Any:
    """Parse the first JSON object or array found in ``text``.

    Handles: bare JSON, ```json fences, and JSON embedded in prose. Raises
    ``EngineeringError`` if no valid JSON can be extracted.
    """
    if text is None:
        raise EngineeringError("Cannot parse JSON from None")
    text = text.strip()

    # Fast path: the whole thing is JSON.
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        pass

    # Strip markdown code fences if present.
    fenced = _strip_fence(text)
    if fenced is not text:
        try:
            return json.loads(fenced)
        except (json.JSONDecodeError, ValueError):
            pass

    obj = _extract_balanced(text, "{", "}")
    if obj is not None:
        return obj
    arr = _extract_balanced(text, "[", "]")
    if arr is not None:
        return arr

    raise EngineeringError("No JSON object or array found in LLM response")


def _strip_fence(text: str) -> str:
    start = text.find("```")
    if start == -1:
        return text
    # Drop the opening fence (``` possibly followed by "json").
    after = text.find("\n", start) + 1
    end = text.rfind("```")
    if end <= after:
        return text
    return text[after:end].strip()


def _extract_balanced(text: str, open_ch: str, close_ch: str) -> Any:
    first = text.find(open_ch)
    if first == -1:
        return None
    depth = 0
    in_str = False
    esc = False
    for i in range(first, len(text)):
        ch = text[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == open_ch:
            depth += 1
        elif ch == close_ch:
            depth -= 1
            if depth == 0:
                candidate = text[first : i + 1]
                try:
                    return json.loads(candidate)
                except (json.JSONDecodeError, ValueError):
                    return None
    return None
