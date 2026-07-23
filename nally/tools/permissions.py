"""Declarative permission system — evaluates tool calls against config rules.

Reads nally/config/permissions.json. Three effects per rule:
  "allow" — execute without prompting
  "ask"   — prompt user for approval
  "deny"  — block immediately

Rules are matched against tool input (command string, action, etc.).
For dict rules, last matching pattern wins. Default is "ask".
"""
import json
import re
from pathlib import Path
from ..config import BASE_DIR
from ..utils.logger import logger

_config = None


def _load():
    global _config
    path = BASE_DIR / "nally" / "config" / "permissions.json"
    try:
        if path.exists():
            _config = json.loads(path.read_text(encoding="utf-8"))
            logger.debug(f"Loaded permissions from {path}")
        else:
            logger.warning(f"permissions.json not found at {path}, using defaults")
            _config = {}
    except Exception as e:
        logger.error(f"Failed to load permissions.json: {e}")
        _config = {}


def _match(pattern: str, value: str) -> bool:
    """Simple wildcard matching: * matches zero or more chars, ? matches one."""
    if pattern == "*":
        return True
    regex = re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".")
    return re.fullmatch(regex, value, re.IGNORECASE) is not None


def _build_match_string(tool_name: str, tool_args: dict) -> str:
    """Extract the string to match rules against from tool arguments."""
    if tool_name == "run_command":
        return tool_args.get("command", "")
    elif tool_name == "file_ops":
        return tool_args.get("action", "")
    elif tool_name == "run_code":
        return tool_args.get("action", "")
    elif tool_name == "code_analysis":
        return tool_args.get("action", "")
    else:
        # For other tools, concat all string arg values
        return " ".join(str(v) for v in tool_args.values() if isinstance(v, str))


def check(tool_name: str, tool_args: dict) -> str:
    """Check permission for a tool call.

    Returns:
        "allow" — skip approval gate, execute immediately
        "ask"   — prompt user for approval (current behavior)
        "deny"  — block immediately, return error to LLM
    """
    if _config is None:
        _load()

    rules = _config.get(tool_name)

    # Unknown tool → ask
    if rules is None:
        return "ask"

    # Simple string rule: "allow" / "ask" / "deny"
    if isinstance(rules, str):
        return rules

    # Dict rules: match against tool input, last match wins
    if isinstance(rules, dict):
        match_value = _build_match_string(tool_name, tool_args)
        result = "ask"  # default if no pattern matches
        for pattern, effect in rules.items():
            if _match(pattern, match_value):
                result = effect
        return result

    return "ask"


def get_config() -> dict:
    """Return the current permission config (for API endpoint)."""
    if _config is None:
        _load()
    return _config or {}


def reload():
    """Force reload config (after user edits permissions.json)."""
    global _config
    _config = None
    _load()
