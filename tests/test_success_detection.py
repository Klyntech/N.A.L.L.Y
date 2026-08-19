"""Tests for orchestration fixes: reliable tool success detection + self-correction shim.

Covers:
- registry._result_is_success (authoritative success from Error prefix + run_command exit code)
- llm.call_llm back-compat shim (reactivates the verification self-correction path)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nally.tools.registry import _result_is_success
from nally.agent.llm import call_llm


def test_error_prefix_is_failure():
    assert _result_is_success("read_file", "Error: File not found: x") is False
    assert _result_is_success("file_ops", "Error: Directory not found: x") is False
    assert _result_is_success("file_ops", "Error: Unknown action: fry") is False


def test_ordinary_content_is_success():
    # Loose words like "error" in legitimate file content must NOT fail.
    assert _result_is_success("read_file", "handle the error case in the parser") is True
    assert _result_is_success("file_ops", "Wrote 12 chars to x") is True
    assert _result_is_success("any_tool", "") is True


def test_run_command_exit_code_is_authoritative():
    assert _result_is_success("run_command", "hello\nExit code: 0") is True
    assert _result_is_success("run_command", "\nExit code: 1") is False
    assert _result_is_success("run_command", "warning: boom\nExit code: 2") is False


def test_call_llm_shim_is_callable():
    # The verification self-correction path imports `call_llm` from nally.agent.llm.
    assert callable(call_llm)
