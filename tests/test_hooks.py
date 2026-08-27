"""Tests for nally.core.hooks — Phase 3.1."""

import json
from pathlib import Path

from nally.core.hooks.manager import HookManager
from nally.core.hooks.models import HookEvent


def _py_cmd(code: str) -> str:
    # Use python with -c, avoid shell quoting issues by using double quotes outer on Windows
    import sys
    # Escape inner double quotes and backslashes for cmd
    # Use sys.executable explicitly
    exe = sys.executable.replace("\\", "/")
    # Wrap code in single quotes for python -c on Windows cmd: python -c "code"
    # Use base64 to avoid quoting hell
    import base64
    b64 = base64.b64encode(code.encode()).decode()
    return f'{exe} -c "import base64,sys,json; exec(base64.b64decode(\'{b64}\').decode())"'


def test_hooks_load(tmp_path: Path):
    deny_code = "import sys,json; data=json.load(sys.stdin); print(json.dumps({'hookSpecificOutput': {'permissionDecision': 'deny', 'permissionDecisionReason': 'nope'}}))"
    hooks_file = tmp_path / "hooks.json"
    hooks_file.write_text(json.dumps({
        "hooks": [
            {"name": "deny-all", "event": "PreToolUse", "matcher": "run_command", "command": _py_cmd(deny_code), "description": "test"},
        ]
    }))
    mgr = HookManager(hooks_path=hooks_file)
    res = mgr.run_pre_tool("run_command", {"command": "rm -rf /"})
    assert res.decision == "deny"
    assert "nope" in (res.reason or "")


def test_hooks_allow_passthrough(tmp_path: Path):
    allow_code = "import sys,json; data=json.load(sys.stdin); print(json.dumps({'hookSpecificOutput': {'permissionDecision': 'allow'}}))"
    hooks_file = tmp_path / "hooks.json"
    hooks_file.write_text(json.dumps({
        "hooks": [
            {"name": "allow", "event": "PreToolUse", "matcher": "*", "command": _py_cmd(allow_code)},
        ]
    }))
    mgr = HookManager(hooks_path=hooks_file)
    res = mgr.run_pre_tool("read_file", {"file_path": "a.txt"})
    assert res.decision == "allow"


def test_hooks_post_tool_context(tmp_path: Path):
    post_code = "import sys,json; json.load(sys.stdin); print(json.dumps({'hookSpecificOutput': {'additionalContext': 'lint ok'}}))"
    hooks_file = tmp_path / "hooks.json"
    hooks_file.write_text(json.dumps({
        "hooks": [
            {"name": "post", "event": "PostToolUse", "matcher": "file_ops", "command": _py_cmd(post_code)},
        ]
    }))
    mgr = HookManager(hooks_path=hooks_file)
    res = mgr.run_post_tool("file_ops", {"action": "write"}, tool_output="wrote", tool_success=True)
    assert res.additionalContext == "lint ok"


def test_hooks_tool_pattern_match(tmp_path: Path):
    deny_code = "import sys,json; d=json.load(sys.stdin); print(json.dumps({'hookSpecificOutput': {'permissionDecision': 'deny', 'permissionDecisionReason': 'no push'}}))"
    hooks_file = tmp_path / "hooks.json"
    hooks_file.write_text(json.dumps({
        "hooks": [
            {"name": "git-deny", "event": "PreToolUse", "matcher": "run_command(git push *)", "command": _py_cmd(deny_code)},
        ]
    }))
    mgr = HookManager(hooks_path=hooks_file)
    res = mgr.run_pre_tool("run_command", {"command": "git push origin master"})
    assert res.decision == "deny"
    res2 = mgr.run_pre_tool("run_command", {"command": "git status"})
    assert res2.decision == "allow"


def test_hooks_manager_singleton():
    from nally.core.hooks.manager import get_hook_manager
    m1 = get_hook_manager()
    m2 = get_hook_manager()
    assert m1 is m2
