"""Declarative permission system — evaluates tool calls against config rules.

Three effects per rule:
  "allow" — execute without prompting
  "ask"   — prompt user for approval
  "deny"  — block immediately

Rules match against tool input (command string, action, etc.).
For dict rules, last matching pattern wins. Default is "ask".

Usage:
    from nally.tools.permissions import gate

    decision = gate.check("run_command", {"command": "rm -rf /"})
    # -> PermissionDecision.DENY

    result = gate.enforce("run_command", {"command": "git status"})
    # -> "allow" (skips approval)
"""

import json
import re
from enum import StrEnum
from pathlib import Path
from typing import Optional

from ..config import BASE_DIR
from ..core.errors import PermissionDenied
from ..utils.logger import logger


class PermissionDecision(StrEnum):
    """Outcome of a permission check."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


# ── Match string extraction ───────────────────────────────

# Maps tool name → which arg to match against
_MATCH_KEY = {
    "run_command": "command",
    "file_ops": "action",
    "run_code": "action",
    "code_analysis": "action",
}


def _extract_match_value(tool_name: str, tool_args: dict) -> str:
    """Extract the string to match rules against from tool arguments."""
    key = _MATCH_KEY.get(tool_name)
    if key and key in tool_args:
        return str(tool_args[key])
    # Fallback: concat all string arg values
    return " ".join(str(v) for v in tool_args.values() if isinstance(v, str))


def _wildcard_match(pattern: str, value: str) -> bool:
    """Simple wildcard matching: * matches zero or more chars, ? matches one."""
    if pattern == "*":
        return True
    regex = re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".")
    return re.fullmatch(regex, value, re.IGNORECASE) is not None


# ── Permission Gate ───────────────────────────────────────


class PermissionGate:
    """Evaluates tool calls against declarative permission rules.

    Thread-safe: config is loaded once and immutable after that.
    Call `reload()` to pick up changes to permissions.json.
    """

    def __init__(self, config_path: Optional[Path] = None):
        self._config_path = config_path or (BASE_DIR / "nally" / "config" / "permissions.json")
        self._config: Optional[dict] = None
        self._skill_overrides: dict[str, list[str]] = {}  # skill_name -> [tool_names]

    def _ensure_loaded(self):
        if self._config is None:
            self._load()

    def _load(self):
        try:
            if self._config_path.exists():
                self._config = json.loads(self._config_path.read_text(encoding="utf-8"))
                logger.debug(f"Loaded permissions from {self._config_path}")
            else:
                logger.warning(f"permissions.json not found at {self._config_path}, using defaults")
                self._config = {}
        except Exception as e:
            logger.error(f"Failed to load permissions.json: {e}")
            self._config = {}

    def reload(self):
        """Force reload config (after user edits permissions.json)."""
        self._config = None
        self._ensure_loaded()

    def check(self, tool_name: str, tool_args: dict) -> PermissionDecision:
        """Check permission for a tool call without enforcing.

        Returns:
            PermissionDecision.ALLOW — safe to execute
            PermissionDecision.ASK — needs user approval
            PermissionDecision.DENY — blocked
        """
        self._ensure_loaded()
        assert self._config is not None

        # Check skill overrides first — active skills grant their allowed-tools
        for _skill_name, allowed_tools in self._skill_overrides.items():
            if tool_name in allowed_tools:
                return PermissionDecision.ALLOW

        rules = self._config.get(tool_name)

        # Exact match not found — try wildcard patterns (e.g. mcp_*)
        if rules is None:
            for pattern, pattern_rules in self._config.items():
                if _wildcard_match(pattern, tool_name):
                    rules = pattern_rules
                    break

        # Unknown tool → ask
        if rules is None:
            return PermissionDecision.ASK

        # Simple string rule: "allow" / "ask" / "deny"
        if isinstance(rules, str):
            try:
                return PermissionDecision(rules)
            except ValueError:
                return PermissionDecision.ASK

        # Dict rules: match against tool input, last match wins
        if isinstance(rules, dict):
            match_value = _extract_match_value(tool_name, tool_args)
            result = PermissionDecision.ASK
            for pattern, effect in rules.items():
                if _wildcard_match(pattern, match_value):
                    try:
                        result = PermissionDecision(effect)
                    except ValueError:
                        result = PermissionDecision.ASK
            return result

        return PermissionDecision.ASK

    def enforce(self, tool_name: str, tool_args: dict) -> PermissionDecision:
        """Check permission and raise PermissionDenied for DENY decisions.

        Same as check() but raises an error for denied operations.
        Use this when you want to block denied tools immediately.

        Returns:
            PermissionDecision.ALLOW or PermissionDecision.ASK

        Raises:
            PermissionDenied: if decision is DENY
        """
        decision = self.check(tool_name, tool_args)
        if decision == PermissionDecision.DENY:
            raise PermissionDenied.denied(tool_name)
        return decision

    def get_config(self) -> dict:
        """Return the current permission config (for API endpoint)."""
        self._ensure_loaded()
        return self._config or {}

    def set_skill_overrides(self, skill_name: str, allowed_tools: list[str]):
        """Temporarily allow tools for an active skill.

        When a skill is activated, its allowed-tools are added here.
        Call clear_skill_overrides() when the skill task is done.
        """
        self._skill_overrides[skill_name] = allowed_tools

    def clear_skill_overrides(self, skill_name: str):
        """Remove skill overrides after task completion."""
        self._skill_overrides.pop(skill_name, None)

    def clear_all_skill_overrides(self):
        """Remove all skill overrides."""
        self._skill_overrides.clear()


# ── Singleton ─────────────────────────────────────────────

gate = PermissionGate()


# ── Backward-compatible functions ──────────────────────────


def check(tool_name: str, tool_args: dict) -> str:
    """Check permission. Returns "allow", "ask", or "deny" as strings."""
    return gate.check(tool_name, tool_args).value


def reload():
    """Force reload permission config."""
    gate.reload()


def get_config() -> dict:
    """Return the current permission config."""
    return gate.get_config()
