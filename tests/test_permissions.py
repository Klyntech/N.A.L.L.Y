"""Tests for permission gate: rule matching, deny/allow logic, skill overrides."""

import json
import tempfile
from pathlib import Path

import pytest

from nally.tools.permissions import PermissionDecision, PermissionGate, _wildcard_match


# ── Wildcard Matching ──────────────────────────────────────


def test_wildcard_exact_match():
    """Exact string match returns True."""
    assert _wildcard_match("ls", "ls") is True


def test_wildcard_star_matches_empty():
    """Pattern '*' matches empty string."""
    assert _wildcard_match("*", "") is True


def test_wildcard_star_matches_anything():
    """Pattern '*' matches any string."""
    assert _wildcard_match("*", "anything at all") is True


def test_wildcard_question_matches_one_char():
    """Pattern '?' matches exactly one character."""
    assert _wildcard_match("a?c", "abc") is True
    assert _wildcard_match("a?c", "aXc") is True
    assert _wildcard_match("a?c", "abbc") is False
    assert _wildcard_match("a?c", "ac") is False


def test_wildcard_star_in_middle():
    """Pattern 'git push *' matches 'git push origin main'."""
    assert _wildcard_match("git push *", "git push origin main") is True
    assert _wildcard_match("git push *", "git push") is False


def test_wildcard_case_insensitive():
    """Wildcard matching is case-insensitive."""
    assert _wildcard_match("LS", "ls") is True
    assert _wildcard_match("ls", "LS") is True


# ── Permission Gate with Custom Config ─────────────────────


@pytest.fixture
def gate_from_tmp():
    """Create a PermissionGate with a temporary permissions.json."""

    def _make(config: dict) -> PermissionGate:
        fd, path = tempfile.mkstemp(suffix=".json")
        with open(path, "w") as f:
            json.dump(config, f)
        g = PermissionGate(config_path=Path(path))
        g.reload()
        return g

    yield _make


# ── (a) Deny pattern blocks exact and case-variant commands ──


def test_deny_blocks_exact_command(gate_from_tmp):
    """Deny rule blocks the exact command string."""
    config = {"run_command": {"*": "ask", "rm -rf /": "deny"}}
    g = gate_from_tmp(config)
    result = g.check("run_command", {"command": "rm -rf /"})
    assert result == PermissionDecision.DENY


def test_deny_blocks_case_variant(gate_from_tmp):
    """Deny rule blocks case-variant because matching is case-insensitive."""
    config = {"run_command": {"*": "ask", "rm -rf /": "deny"}}
    g = gate_from_tmp(config)
    result = g.check("run_command", {"command": "RM -RF /"})
    assert result == PermissionDecision.DENY


def test_deny_blocks_wildcard_pattern(gate_from_tmp):
    """Deny with wildcard blocks matching subcommands."""
    config = {"run_command": {"*": "ask", "rm -rf *": "deny"}}
    g = gate_from_tmp(config)
    result = g.check("run_command", {"command": "rm -rf /tmp"})
    assert result == PermissionDecision.DENY


# ── (b) Chained commands do NOT inherit an allow rule ──────


def test_chained_command_does_not_get_allow(gate_from_tmp):
    """'ls; rm -rf /' does NOT match 'ls' allow rule (last match wins for full string)."""
    config = {"run_command": {"*": "ask", "ls": "allow", "rm -rf /": "deny"}}
    g = gate_from_tmp(config)
    result = g.check("run_command", {"command": "ls; rm -rf /"})
    assert result != PermissionDecision.ALLOW


def test_chained_command_matches_default_ask(gate_from_tmp):
    """'ls; rm -rf /' falls through to default ask since no exact pattern matches."""
    config = {"run_command": {"*": "ask", "ls": "allow", "rm -rf /": "deny"}}
    g = gate_from_tmp(config)
    result = g.check("run_command", {"command": "ls; rm -rf /"})
    assert result == PermissionDecision.ASK


def test_chained_with_deny_pattern(gate_from_tmp):
    """'ls; rm -rf /' hits the deny rule if it matches the pattern."""
    config = {"run_command": {"*": "ask", "ls": "allow", "rm -rf *": "deny"}}
    g = gate_from_tmp(config)
    result = g.check("run_command", {"command": "ls; rm -rf /"})
    # The full string "ls; rm -rf /" doesn't match "rm -rf *" exactly,
    # so last match is "rm -rf *" -> deny... actually "ls; rm -rf /" vs "rm -rf *"
    # The _wildcard_match uses re.fullmatch, so "ls; rm -rf /" won't match "rm -rf *"
    # Last match is "*" -> ask
    assert result == PermissionDecision.ASK


def test_pipe_command_does_not_inherit_allow(gate_from_tmp):
    """'cat file | rm -rf /' does not inherit 'cat' allow."""
    config = {"run_command": {"*": "ask", "cat": "allow", "rm -rf /": "deny"}}
    g = gate_from_tmp(config)
    result = g.check("run_command", {"command": "cat file | rm -rf /"})
    assert result != PermissionDecision.ALLOW


# ── (c) Unknown tool defaults to "ask" ─────────────────────


def test_unknown_tool_returns_ask(gate_from_tmp):
    """Tool not present in config returns ASK."""
    config = {"run_command": {"*": "ask"}}
    g = gate_from_tmp(config)
    result = g.check("unknown_tool", {"arg": "value"})
    assert result == PermissionDecision.ASK


def test_empty_config_returns_ask(gate_from_tmp):
    """Empty config returns ASK for any tool."""
    g = gate_from_tmp({})
    result = g.check("run_command", {"command": "ls"})
    assert result == PermissionDecision.ASK


# ── (d) Skill overrides grant allow correctly ───────────────


def test_skill_override_grants_allow(gate_from_tmp):
    """Skill override grants ALLOW for a tool that would otherwise be ASK."""
    config = {"run_command": {"*": "ask"}}
    g = gate_from_tmp(config)
    g.set_skill_overrides("my_skill", ["run_command"])
    result = g.check("run_command", {"command": "rm -rf /"})
    assert result == PermissionDecision.ALLOW


def test_skill_override_does_not_affect_other_tools(gate_from_tmp):
    """Skill override only affects listed tools."""
    config = {"run_command": {"*": "ask"}, "file_ops": "allow"}
    g = gate_from_tmp(config)
    g.set_skill_overrides("my_skill", ["run_command"])
    # run_command is overridden -> allow
    assert g.check("run_command", {"command": "anything"}) == PermissionDecision.ALLOW
    # file_ops is not overridden, but has its own allow rule
    assert g.check("file_ops", {"action": "write"}) == PermissionDecision.ALLOW


def test_clear_skill_override_restores_normal(gate_from_tmp):
    """Clearing skill override restores normal permission behavior."""
    config = {"run_command": {"*": "ask"}}
    g = gate_from_tmp(config)
    g.set_skill_overrides("my_skill", ["run_command"])
    assert g.check("run_command", {"command": "ls"}) == PermissionDecision.ALLOW
    g.clear_skill_overrides("my_skill")
    assert g.check("run_command", {"command": "ls"}) == PermissionDecision.ASK


def test_clear_all_skill_overrides(gate_from_tmp):
    """clear_all_skill_overrides removes all overrides."""
    config = {"run_command": {"*": "ask"}}
    g = gate_from_tmp(config)
    g.set_skill_overrides("skill_a", ["run_command"])
    g.set_skill_overrides("skill_b", ["file_ops"])
    g.clear_all_skill_overrides()
    assert g.check("run_command", {"command": "ls"}) == PermissionDecision.ASK
    assert g.check("file_ops", {"action": "write"}) == PermissionDecision.ASK


# ── Enforce method ─────────────────────────────────────────


def test_enforce_raises_on_deny(gate_from_tmp):
    """enforce() raises PermissionDenied for DENY decisions."""
    from nally.core.errors import PermissionDenied

    config = {"run_command": {"*": "ask", "rm -rf /": "deny"}}
    g = gate_from_tmp(config)
    with pytest.raises(PermissionDenied):
        g.enforce("run_command", {"command": "rm -rf /"})


def test_enforce_returns_on_allow(gate_from_tmp):
    """enforce() returns normally for ALLOW decisions."""
    config = {"run_command": {"ls": "allow"}}
    g = gate_from_tmp(config)
    result = g.enforce("run_command", {"command": "ls"})
    assert result == PermissionDecision.ALLOW


def test_enforce_returns_on_ask(gate_from_tmp):
    """enforce() returns ASK (does not raise) for ASK decisions."""
    config = {"run_command": {"*": "ask"}}
    g = gate_from_tmp(config)
    result = g.enforce("run_command", {"command": "unknown"})
    assert result == PermissionDecision.ASK


# ── Last-match-wins ordering ───────────────────────────────


def test_last_matching_pattern_wins(gate_from_tmp):
    """In dict rules, the last matching pattern determines the outcome."""
    config = {"run_command": {"*": "ask", "git push *": "allow", "git push *--force*": "deny"}}
    g = gate_from_tmp(config)
    # Normal push matches both "git push *" (allow) and last is deny for force
    assert g.check("run_command", {"command": "git push origin main"}) == PermissionDecision.ALLOW
    # Force push matches "git push *--force*" -> deny
    assert g.check("run_command", {"command": "git push --force origin main"}) == PermissionDecision.DENY


# ── String rule (non-dict) ─────────────────────────────────


def test_simple_string_rule_allow(gate_from_tmp):
    """Simple string rule 'allow' returns ALLOW for any args."""
    config = {"file_ops": "allow"}
    g = gate_from_tmp(config)
    assert g.check("file_ops", {"action": "write"}) == PermissionDecision.ALLOW


def test_simple_string_rule_deny(gate_from_tmp):
    """Simple string rule 'deny' returns DENY for any args."""
    config = {"generate_image": "deny"}
    g = gate_from_tmp(config)
    assert g.check("generate_image", {"prompt": "test"}) == PermissionDecision.DENY


def test_malformed_string_rule_falls_back_to_ask(gate_from_tmp):
    """Malformed string rule returns ASK."""
    config = {"some_tool": "bogus_value"}
    g = gate_from_tmp(config)
    assert g.check("some_tool", {}) == PermissionDecision.ASK
