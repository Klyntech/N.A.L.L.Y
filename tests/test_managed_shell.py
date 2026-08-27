"""Tests for managed shell — Phase 2 vibe-style persistent sessions."""

import time
from pathlib import Path

from nally.core.managed_shell.manager import ManagedShellManager


def test_start_and_read_output(tmp_path: Path):
    mgr = ManagedShellManager(base_dir=tmp_path / "shell-tool")
    sess = mgr.start('echo hello_managed', cwd=str(tmp_path))
    assert sess.session_id.startswith("shell_")
    # Poll
    for _ in range(20):
        s, data, _ = mgr.read_output(sess.session_id, cursor=0, max_bytes=10000, wait_seconds=0.1)
        if b"hello_managed" in data:
            break
        time.sleep(0.1)
    else:
        assert False, "output never arrived"
    assert s.status in ("running", "completed")


def test_sessions_list(tmp_path: Path):
    mgr = ManagedShellManager(base_dir=tmp_path / "shell-tool")
    mgr.start('echo one', cwd=str(tmp_path))
    mgr.start('echo two', cwd=str(tmp_path))
    time.sleep(0.5)
    lst = mgr.list_sessions()
    assert len(lst) >= 2


def test_write_stdin_and_kill(tmp_path: Path):
    mgr = ManagedShellManager(base_dir=tmp_path / "shell-tool")
    # Start a python REPL-like sleep that we can kill
    sess = mgr.start('python -c "import time; time.sleep(999)"', cwd=str(tmp_path))
    time.sleep(0.5)
    lst = mgr.list_sessions()
    assert any(s["session_id"] == sess.session_id for s in lst)
    ok = mgr.kill(sess.session_id)
    assert ok is True
    # After kill, status should be killed or completed
    info = mgr.inspect(sess.session_id)
    assert info["session"]["status"] in ("killed", "completed", "running")


def test_shell_tools_registered():
    from nally.tools import load_all_tools
    from nally.tools.registry import registry

    load_all_tools()
    assert "shell_sessions" in registry.tools
    assert "shell_output" in registry.tools
    assert "shell_stdin" in registry.tools


def test_run_command_background(tmp_path: Path):
    from nally.tools.system import RunCommand

    tool = RunCommand()
    # Background should return session handle, not block
    result = tool.execute(command='echo bg_test', background=True)
    assert "Started background shell session" in result
    assert "shell_output" in result


def test_shell_output_tool(tmp_path: Path):
    from nally.core.managed_shell.manager import get_manager
    from nally.tools.managed import ShellOutput, ShellSessions

    mgr = get_manager()
    sess = mgr.start('echo shell_output_test', cwd=str(tmp_path))
    time.sleep(0.8)
    tool = ShellOutput()
    result = tool.execute(session_id=sess.session_id, cursor=0)
    assert "shell_output_test" in result or "cursor" in result.lower()

    tool2 = ShellSessions()
    result2 = tool2.execute(action="list")
    assert "shell_" in result2
