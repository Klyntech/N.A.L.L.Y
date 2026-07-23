"""Code Execution and Analysis Tools"""
import sys
import io
import subprocess
from pathlib import Path
from .registry import Tool, registry


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
        try:
            if action == "execute":
                if not code:
                    return "Error: code is required for execute"
                old_stdout = sys.stdout
                old_stderr = sys.stderr
                sys.stdout = io.StringIO()
                sys.stderr = io.StringIO()
                exec(code, {"__builtins__": __builtins__})
                output = sys.stdout.getvalue()
                error = sys.stderr.getvalue()
                sys.stdout = old_stdout
                sys.stderr = old_stderr
                if error:
                    return f"Output:\n{output}\nErrors:\n{error}"
                return f"Output:\n{output}" if output else "Code executed successfully (no output)"

            elif action == "run_file":
                if not file_path:
                    return "Error: file_path is required for run_file"
                result = subprocess.run(
                    [sys.executable, file_path],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                output = result.stdout
                if result.stderr:
                    output += f"\nStderr: {result.stderr}"
                return output if output else "Script executed successfully"

            else:
                return f"Unknown action: {action}. Use execute or run_file."
        except subprocess.TimeoutExpired:
            return "Script timed out after 60 seconds"
        except Exception as e:
            sys.stdout = sys.__stdout__
            sys.stderr = sys.__stderr__
            return f"Error: {str(e)}"


class CodeAnalysis(Tool):
    def __init__(self):
        super().__init__(
            name="code_analysis",
            description="Run tests or analyze code",
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
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                output = result.stdout
                if result.stderr:
                    output += f"\n{result.stderr}"
                if output:
                    return output
                # Fallback to unittest
                cmd = [sys.executable, "-m", "unittest", "discover"]
                if path:
                    cmd = [sys.executable, "-m", "unittest", path]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                return result.stdout or "Tests completed"

            elif action == "lint":
                target = path or "."
                # Try flake8 first, fall back to pylint
                for linter in ["flake8", "pylint"]:
                    cmd = [sys.executable, "-m", linter, target]
                    if linter == "flake8" and not verbose:
                        cmd.append("--quiet")
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
                    if result.returncode != 127:  # not "command not found"
                        output = result.stdout
                        if result.stderr:
                            output += f"\n{result.stderr}"
                        return output or f"No issues found with {linter}"
                return "No linter available (install flake8 or pylint)"

            else:
                return f"Unknown action: {action}. Use test or lint."
        except subprocess.TimeoutExpired:
            return "Analysis timed out after 120 seconds"
        except Exception as e:
            return f"Error: {str(e)}"
