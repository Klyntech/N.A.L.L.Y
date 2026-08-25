"""Tests for nally.tools.code — RunCode exec timeout and CodeAnalysis."""

import pytest
from nally.tools.code import RunCode, CodeAnalysis, CODE_TIMEOUT


@pytest.fixture
def run_code():
    return RunCode()


@pytest.fixture
def code_analysis():
    return CodeAnalysis()


class TestRunCodeExecute:
    def test_simple_execution(self, run_code):
        result = run_code.execute(action="execute", code="print('hello world')")
        assert "hello world" in result

    def test_no_output(self, run_code):
        result = run_code.execute(action="execute", code="x = 1 + 2")
        assert "successfully" in result.lower() or "output" in result.lower()

    def test_syntax_error(self, run_code):
        result = run_code.execute(action="execute", code="def foo(")
        assert "Exception" in result or "SyntaxError" in result

    def test_empty_code(self, run_code):
        result = run_code.execute(action="execute", code="")
        assert "Error" in result

    def test_exec_timeout(self, run_code):
        """Code running longer than CODE_TIMEOUT should be terminated."""
        result = run_code.execute(action="execute", code="import time; time.sleep(999)")
        assert "timed out" in result.lower()

    def test_infinite_loop_timeout(self, run_code):
        """An infinite while loop should be caught by the timeout."""
        result = run_code.execute(action="execute", code="while True: pass")
        assert "timed out" in result.lower()

    def test_sys_exit_handled(self, run_code):
        result = run_code.execute(action="execute", code="import sys; sys.exit(0)")
        assert "sys.exit()" in result

    def test_print_before_error(self, run_code):
        """Output before an exception should be captured."""
        result = run_code.execute(action="execute", code="print('partial'); raise ValueError('boom')")
        assert "partial" in result
        assert "ValueError" in result


class TestRunCodeRunFile:
    def test_run_nonexistent_file(self, run_code):
        result = run_code.execute(action="run_file", file_path="/nonexistent/file.py")
        assert "Error" in result
        assert "not found" in result.lower()

    def test_run_empty_path(self, run_code):
        result = run_code.execute(action="run_file", file_path="")
        assert "Error" in result

    def test_unknown_action(self, run_code):
        result = run_code.execute(action="unknown")
        assert "Unknown action" in result


class TestCodeAnalysis:
    def test_unknown_action(self, code_analysis):
        result = code_analysis.execute(action="unknown")
        assert "Unknown action" in result
