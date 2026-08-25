"""Tests for nally.tools.system — RunCommand and SystemHealth."""

import platform
import pytest
from unittest.mock import patch
from nally.tools.system import RunCommand, SystemHealth, _get_shell, _normalize_powershell


@pytest.fixture
def run_command():
    return RunCommand()


@pytest.fixture
def system_health():
    return SystemHealth()


class TestGetShell:
    def test_returns_tuple(self):
        result = _get_shell()
        assert isinstance(result, tuple)
        assert len(result) == 2
        executable, args = result
        assert isinstance(executable, str)
        assert isinstance(args, list)

    @patch("nally.tools.system.platform.system", return_value="Windows")
    @patch("nally.tools.system.shutil.which", return_value="C:\\Program Files\\PowerShell\\7\\pwsh.exe")
    def test_windows_prefers_pwsh(self, mock_which, mock_platform):
        executable, args = _get_shell()
        assert "pwsh" in executable.lower() or "powershell" in executable.lower()

    @patch("nally.tools.system.platform.system", return_value="Linux")
    def test_linux_uses_bash(self, mock_platform):
        executable, args = _get_shell()
        assert executable == "/bin/bash"
        assert args == ["-c"]


class TestNormalizePowershell:
    def test_double_ampersand(self):
        result = _normalize_powershell("echo hello && echo world")
        assert "if ($?)" in result
        assert "echo hello" in result
        assert "echo world" in result

    def test_triple_ampersand(self):
        result = _normalize_powershell("a && b && c")
        assert result.count("if ($?)") == 2

    def test_no_change_for_clean_command(self):
        cmd = "Get-Process"
        result = _normalize_powershell(cmd)
        assert result == cmd


class TestRunCommand:
    def test_empty_command(self, run_command):
        result = run_command.execute(command="")
        assert "Error" in result

    def test_simple_command(self, run_command):
        result = run_command.execute(command="echo hello")
        assert "hello" in result.lower()

    def test_invalid_command(self, run_command):
        result = run_command.execute(command="nonexistent_command_xyz")
        assert "Error" in result or "Exit code" in result


class TestSystemHealth:
    def test_returns_string(self, system_health):
        result = system_health.execute()
        assert isinstance(result, str)
        # Should either have health data or an error/missing dep message
        assert "CPU" in result or "requires" in result.lower() or "Error" in result
