"""Code Execution and Analysis Tools"""

import io
import os
import subprocess
import sys
import threading
from pathlib import Path

from .registry import Tool

# Reuse system.py's configurable timeout
CODE_TIMEOUT = int(os.environ.get("NALLY_CMD_TIMEOUT", "60"))

# Thread lock for stdout/stderr hijacking (not thread-safe otherwise)
_code_exec_lock = threading.Lock()


class RunCode(Tool):
    def __init__(self):
        super().__init__(
            name="run_code",
            description="Execute Python code or run a Python file",
            permission="destructive",
            parameters={
                "action": {
                    "type": "string",
                    "enum": ["execute", "run_file"],
                    "description": "execute = run code snippet, run_file = run a .py file",
                    "required": True,
                },
                "code": {
                    "type": "string",
                    "description": "Python code to execute (for action=execute)",
                },
                "file_path": {
                    "type": "string",
                    "description": "Path to .py file (for action=run_file)",
                },
            },
        )

    def execute(self, action: str, code: str = "", file_path: str = "", **kwargs) -> str:
        if action == "execute":
            return self._execute_code(code)
        elif action == "run_file":
            return self._run_file(file_path)
        else:
            return f"Unknown action: {action}. Use execute or run_file."

    def _execute_code(self, code: str) -> str:
        if not code:
            return "Error: code is required for execute"

        with _code_exec_lock:
            old_stdout = sys.stdout
            old_stderr = sys.stderr
            stdout_capture = io.StringIO()
            stderr_capture = io.StringIO()
            sys.stdout = stdout_capture
            sys.stderr = stderr_capture
            try:
                exec(code, {"__builtins__": __builtins__})
                output = stdout_capture.getvalue()
                error = stderr_capture.getvalue()
                if error:
                    return f"Output:\n{output}\nErrors:\n{error}"
                return f"Output:\n{output}" if output else "Code executed successfully (no output)"
            except SystemExit:
                output = stdout_capture.getvalue()
                return f"Output:\n{output}\nScript called sys.exit()"
            except Exception as e:
                output = stdout_capture.getvalue()
                error = stderr_capture.getvalue()
                parts = []
                if output:
                    parts.append(f"Output:\n{output}")
                if error:
                    parts.append(f"Errors:\n{error}")
                parts.append(f"Exception: {type(e).__name__}: {e}")
                return "\n".join(parts)
            finally:
                sys.stdout = old_stdout
                sys.stderr = old_stderr

    def _run_file(self, file_path: str) -> str:
        if not file_path:
            return "Error: file_path is required for run_file"
        path = Path(file_path)
        if not path.exists():
            return f"Error: file not found: {file_path}"
        try:
            result = subprocess.run(
                [sys.executable, str(path.resolve())],
                capture_output=True,
                text=True,
                timeout=CODE_TIMEOUT,
                cwd=str(path.parent),
            )
            output = result.stdout
            if result.stderr:
                output += f"\nStderr: {result.stderr}"
            if result.returncode != 0:
                return f"Exit code {result.returncode}\n{output}" if output else f"Exit code {result.returncode}"
            return output if output else "Script executed successfully"
        except subprocess.TimeoutExpired:
            return f"Script timed out after {CODE_TIMEOUT} seconds"


class CodeAnalysis(Tool):
    def __init__(self):
        super().__init__(
            name="code_analysis",
            description="Run tests or lint code",
            parameters={
                "action": {
                    "type": "string",
                    "enum": ["test", "lint"],
                    "description": "test = run pytest/unittest, lint = run pylint/flake8",
                    "required": True,
                },
                "path": {
                    "type": "string",
                    "description": "Path to test file or code to lint",
                },
                "verbose": {
                    "type": "boolean",
                    "description": "Show verbose output",
                },
            },
        )

    def execute(self, action: str, path: str = "", verbose: bool = False, **kwargs) -> str:
        try:
            if action == "test":
                cmd = [sys.executable, "-m", "pytest"]
                if path:
                    cmd.append(path)
                cmd.append("-v" if verbose else "-q")
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=CODE_TIMEOUT)
                output = result.stdout
                if result.stderr:
                    output += f"\n{result.stderr}"
                if output:
                    return output
                cmd = [sys.executable, "-m", "unittest", "discover"]
                if path:
                    cmd = [sys.executable, "-m", "unittest", path]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=CODE_TIMEOUT)
                return result.stdout or "Tests completed"

            elif action == "lint":
                target = path or "."
                for linter in ["flake8", "pylint"]:
                    cmd = [sys.executable, "-m", linter, target]
                    if linter == "flake8" and not verbose:
                        cmd.append("--quiet")
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=CODE_TIMEOUT)
                    if result.returncode not in (127, 126):
                        output = result.stdout
                        if result.stderr:
                            output += f"\n{result.stderr}"
                        return output or f"No issues found with {linter}"
                return "No linter available (install flake8 or pylint)"

            else:
                return f"Unknown action: {action}. Use test or lint."
        except subprocess.TimeoutExpired:
            return f"Analysis timed out after {CODE_TIMEOUT} seconds"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"
