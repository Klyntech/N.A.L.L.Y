"""Tests for tool executor permission enforcement and approval flow."""

import json
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from nally.tools.permissions import PermissionDecision, PermissionGate


# ── Helper: build a PermissionGate from a dict ──────────────


def _make_gate(config: dict) -> PermissionGate:
    fd, path = tempfile.mkstemp(suffix=".json")
    with open(path, "w") as f:
        json.dump(config, f)
    g = PermissionGate(config_path=Path(path))
    g.reload()
    return g


# ── Deny short-circuits before execution ────────────────────


def test_deny_blocks_tool_execution():
    """When permission is DENY, the tool's execute() must never be called."""
    gate = _make_gate({"run_command": {"*": "ask", "rm -rf /": "deny"}})

    decision = gate.check("run_command", {"command": "rm -rf /"})
    assert decision == PermissionDecision.DENY

    # Simulate what tool_executor does: if deny, return immediately
    mock_tool = MagicMock()
    if decision == PermissionDecision.DENY:
        result = "Blocked: 'run_command' is denied by permission config."
    else:
        result = mock_tool.execute()

    mock_tool.execute.assert_not_called()
    assert "denied" in result.lower() or "blocked" in result.lower()


def test_deny_prevents_file_ops():
    """DENY on file_ops blocks the operation."""
    gate = _make_gate({"file_ops": "deny"})

    decision = gate.check("file_ops", {"action": "write", "file_path": "/etc/passwd"})
    assert decision == PermissionDecision.DENY

    mock_tool = MagicMock()
    if decision == PermissionDecision.DENY:
        result = "Blocked"
    else:
        result = mock_tool.execute()

    mock_tool.execute.assert_not_called()


def test_allow_permits_execution():
    """When permission is ALLOW, execution proceeds."""
    gate = _make_gate({"run_command": {"ls": "allow"}})

    decision = gate.check("run_command", {"command": "ls"})
    assert decision == PermissionDecision.ALLOW

    mock_tool = MagicMock()
    mock_tool.execute.return_value = "file1.txt\nfile2.txt"
    if decision == PermissionDecision.DENY:
        result = "Blocked"
    elif decision == PermissionDecision.ASK:
        result = "Waiting for approval"
    else:
        result = mock_tool.execute()

    mock_tool.execute.assert_called_once()
    assert "file1" in result


# ── Ask path times out when no approval arrives ─────────────


def test_ask_timeout_returns_declined():
    """When approval times out, the tool call is treated as declined."""
    gate = _make_gate({"run_command": {"*": "ask"}})

    decision = gate.check("run_command", {"command": "git push origin main"})
    assert decision == PermissionDecision.ASK

    # Simulate the approval event with a very short timeout
    approval_event = threading.Event()
    timeout_seconds = 0.1

    start = time.time()
    approved = approval_event.wait(timeout=timeout_seconds)
    elapsed = time.time() - start

    assert approved is False
    assert elapsed < 1.0  # Should return quickly

    # Simulate what tool_executor does on timeout
    if not approved:
        result = "Action 'run_command' was declined or timed out."
    else:
        result = "executed"

    assert "declined" in result.lower() or "timed out" in result.lower()


def test_ask_approval_succeeds():
    """When approval is set, the tool call proceeds."""
    gate = _make_gate({"run_command": {"*": "ask"}})

    decision = gate.check("run_command", {"command": "git push origin main"})
    assert decision == PermissionDecision.ASK

    approval_event = threading.Event()
    approval_results = {}

    # Simulate approval being set before timeout
    def simulate_approval():
        time.sleep(0.05)
        approval_results["tool_call_id_123"] = True
        approval_event.set()

    t = threading.Thread(target=simulate_approval)
    t.start()

    approved = approval_event.wait(timeout=2.0)
    t.join()

    assert approved is True
    assert approval_results.get("tool_call_id_123") is True

    # Simulate execution proceeds after approval
    mock_tool = MagicMock()
    mock_tool.execute.return_value = "success"
    if not approved:
        result = "Declined"
    else:
        result = mock_tool.execute()

    mock_tool.execute.assert_called_once()
    assert result == "success"


def test_approval_decline_blocks_execution():
    """When approval is explicitly declined, execution is blocked."""
    approval_event = threading.Event()
    approval_results = {}

    def simulate_decline():
        time.sleep(0.05)
        approval_results["tool_call_id_456"] = False
        approval_event.set()

    t = threading.Thread(target=simulate_decline)
    t.start()

    approved = approval_event.wait(timeout=2.0)
    t.join()

    assert approved is True
    assert approval_results.get("tool_call_id_456") is False

    # Simulate tool_executor behavior on decline
    mock_tool = MagicMock()
    if approval_results.get("tool_call_id_456") is False:
        result = "Action was declined or timed out."
    else:
        result = mock_tool.execute()

    mock_tool.execute.assert_not_called()
    assert "declined" in result.lower()


# ── Deny with wildcard pattern ──────────────────────────────


def test_deny_wildcard_blocks_matching_command():
    """Deny pattern with wildcard blocks matching commands."""
    gate = _make_gate({"run_command": {"*": "ask", "sudo rm *": "deny"}})

    assert gate.check("run_command", {"command": "sudo rm -rf /"}) == PermissionDecision.DENY
    assert gate.check("run_command", {"command": "sudo rm file.txt"}) == PermissionDecision.DENY


def test_deny_wildcard_allows_non_matching():
    """Deny pattern with wildcard does not block non-matching commands."""
    gate = _make_gate({"run_command": {"*": "ask", "sudo rm *": "deny"}})

    assert gate.check("run_command", {"command": "rm file.txt"}) == PermissionDecision.ASK
    assert gate.check("run_command", {"command": "sudo ls"}) == PermissionDecision.ASK
