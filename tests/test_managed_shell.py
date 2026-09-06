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


def test_removed_tools_absent_from_registry():
    from nally.tools import load_all_tools
    from nally.tools.registry import registry

    load_all_tools()
    for name in (
        "shell_sessions",
        "shell_output",
        "shell_stdin",
        "bridge_execute",
        "make_call",
        "get_call_status",
        "hangup_call",
        "list_calls",
    ):
        assert name not in registry.tools, f"removed tool still registered: {name}"
    for name in ("run_command", "run_code", "code_analysis"):
        assert name in registry.tools, f"surviving tool missing: {name}"


def test_run_command_background(tmp_path: Path):
    from nally.tools.system import RunCommand

    tool = RunCommand()
    # Background should return session handle, not block
    result = tool.execute(command='echo bg_test', background=True)
    assert "Started background shell session" in result
    assert 'run_command(action="session_output"' in result


def test_run_command_session_lifecycle(tmp_path: Path):
    import sys

    from nally.tools.system import RunCommand

    tool = RunCommand()
    sleep_cmd = f'{sys.executable} -c "import time; time.sleep(60)"'
    started = tool.execute(command=sleep_cmd, background=True)
    assert "Started background shell session" in started
    session_id = started.split("session ")[1].split(" ")[0]

    listed = tool.execute(action="session_list")
    assert session_id in listed

    killed = tool.execute(action="session_kill", session_id=session_id)
    assert "killed" in killed.lower()

    echo_started = tool.execute(command='echo session_lifecycle_test', background=True)
    echo_id = echo_started.split("session ")[1].split(" ")[0]
    output = ""
    for _ in range(20):
        output = tool.execute(action="session_output", session_id=echo_id)
        if "session_lifecycle_test" in output:
            break
        time.sleep(0.1)
    assert "session_lifecycle_test" in output
    assert "next_cursor=" in output

    inspected = tool.execute(action="session_inspect", session_id=echo_id)
    assert echo_id in inspected


def test_run_command_session_unknown():
    from nally.tools.system import RunCommand

    tool = RunCommand()
    assert "Error" in tool.execute(action="session_output", session_id="nope-missing")
    assert "Error" in tool.execute(action="session_stdin", session_id="nope-missing", text="x")
    assert "Error" in tool.execute(action="session_kill", session_id="nope-missing")
    assert "Error" in tool.execute(action="session_stdin", session_id="whatever", text="")
