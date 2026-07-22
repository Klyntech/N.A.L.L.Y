"""Code Generation, Execution, and Intelligence Tools"""
import sys
import io
import subprocess
from pathlib import Path
from .registry import Tool, registry

class WriteCode(Tool):
    def __init__(self):
        super().__init__(
            name="write_code",
            description="Generate and save Python code to a file",
            permission="destructive",
            parameters={
                "file_path": {
                    "type": "string",
                    "description": "Path to save the code file",
                    "required": True
                },
                "code": {
                    "type": "string",
                    "description": "Python code to write",
                    "required": True
                }
            }
        )

    def execute(self, file_path: str, code: str) -> str:
        try:
            path = Path(file_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            if not code.startswith('#!'):
                code = "#!/usr/bin/env python3\n" + code
            path.write_text(code, encoding='utf-8')
            return f"Code saved to {file_path}"
        except Exception as e:
            return f"Error saving code: {str(e)}"

class RunCode(Tool):
    def __init__(self):
        super().__init__(
            name="run_code",
            description="Execute a Python code snippet and return output",
            permission="destructive",
            parameters={
                "code": {
                    "type": "string",
                    "description": "Python code to execute",
                    "required": True
                }
            }
        )

    def execute(self, code: str) -> str:
        try:
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
        except Exception as e:
            sys.stdout = old_stdout
            sys.stderr = old_stderr
            return f"Execution error: {str(e)}"

class RunPythonFile(Tool):
    def __init__(self):
        super().__init__(
            name="run_python_file",
            description="Execute a Python file and return output",
            permission="destructive",
            parameters={
                "file_path": {
                    "type": "string",
                    "description": "Path to the Python file to run",
                    "required": True
                }
            }
        )

    def execute(self, file_path: str) -> str:
        try:
            result = subprocess.run(
                [sys.executable, file_path],
                capture_output=True,
                text=True,
                timeout=60
            )
            output = result.stdout
            if result.stderr:
                output += f"\nStderr: {result.stderr}"
            return output if output else "Script executed successfully"
        except subprocess.TimeoutExpired:
            return "Script timed out after 60 seconds"
        except Exception as e:
            return f"Error running script: {str(e)}"

class RunTests(Tool):
    def __init__(self):
        super().__init__(
            name="run_tests",
            description="Run tests using pytest or unittest",
            parameters={
                "path": {
                    "type": "string",
                    "description": "Test path or file to run (default: discover all tests)",
                },
                "verbose": {
                    "type": "boolean",
                    "description": "Show verbose output",
                }
            }
        )

    def execute(self, path: str = "", verbose: bool = False, **kwargs) -> str:
        try:
            cmd = [sys.executable, "-m", "pytest"]
            if path:
                cmd.append(path)
            if verbose:
                cmd.append("-v")
            else:
                cmd.append("-q")

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            output = result.stdout
            if result.stderr:
                output += f"\n{result.stderr}"
            return output if output else "Tests completed"
        except subprocess.TimeoutExpired:
            return "Tests timed out after 120 seconds"
        except FileNotFoundError:
            try:
                cmd = [sys.executable, "-m", "unittest", "discover"]
                if path:
                    cmd = [sys.executable, "-m", "unittest", path]
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                return result.stdout or "Tests completed"
            except Exception as e:
                return f"Test error: {str(e)}"
        except Exception as e:
            return f"Test error: {str(e)}"
