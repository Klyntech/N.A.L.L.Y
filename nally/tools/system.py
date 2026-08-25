"""System Control Tools"""

import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .registry import Tool

# Command timeout (seconds) — configurable via env
CMD_TIMEOUT = int(os.environ.get("NALLY_CMD_TIMEOUT", "60"))


def _normalize_powershell(command: str) -> str:
    """Fix common LLM-generated PowerShell mistakes before execution.

    - `A && B` -> `A; if ($?) { B }`  (PowerShell has no &&)
    - `Select-String -Path X -Recurse` -> `Get-ChildItem -Path X -Recurse -File | Select-String` (Select-String has no -Recurse)
    - Normalizes `;` handling
    """
    original = command

    # Fix && (bash) -> PowerShell ; if ($?) { ... }
    # Count occurrences to close braces correctly: A && B && C -> A; if ($?) { B; if ($?) { C } }
    if " && " in command:
        parts = command.split(" && ")
        # Rebuild as nested if ($?) blocks
        normalized = parts[0]
        for part in parts[1:]:
            normalized += f"; if ($?) {{ {part.strip()} }}"
        # Need to close each opened brace: we opened len(parts)-1 times, but we used `{{` which is single `{` escaped for f-string?
        # Actually we used f"; if ($?) {{ {part} }}" which produces "; if ($?) { part }"
        # So we need to close each: we already closed each with `}`, but nested requires extra `}`?
        # Simpler: just close with ` }` * (len(parts)-1) is already included as each part's closing `}`.
        # For A && B && C, we get: A; if ($?) { B; if ($?) { C } } -> correct (2 opens, 2 closes)
        # Our loop already adds `; if ($?) { part }` for each, so it's already nested correctly.
        # But we need to ensure we didn't double-close: we did `; if ($?) { B }` then `; if ($?) { C }` -> A; if ($?) { B; if ($?) { C } } -> need one more `}`?
        # Actually our loop builds: "A" -> "A; if ($?) { B }" -> "A; if ($?) { B }; if ($?) { C }" which is not nested.
        # Let's rebuild properly nested:
        # A && B && C should be A; if ($?) { B; if ($?) { C } }  (B inside first if, C inside second)
        # Our simple split gives A; if ($?) { B }; if ($?) { C } which runs C even if B fails but A succeeded.
        # To be truly nested, we need to close at end, not per part.
        # Fix: rebuild with proper nesting
        normalized = parts[0]
        for part in parts[1:]:
            normalized += f"; if ($?) {{ {part.strip()}"
        normalized += " }" * (len(parts) - 1)
        command = normalized

    # Fix Select-String -Recurse (invalid) -> Get-ChildItem -Recurse | Select-String
    if "Select-String" in command and "-Recurse" in command:
        # Remove all standalone -Recurse flags (they belong to Get-ChildItem, not Select-String)
        command_without_recurse = re.sub(r'\s+-Recurse\b', '', command)
        # If Get-ChildItem not already present, inject it
        if "Get-ChildItem" not in command_without_recurse:
            # Handle `Select-String -Path <path>` -> `Get-ChildItem -Path <path> -Recurse -File | Select-String`
            m = re.search(r'Select-String\s+-Path\s+([^\s;|]+)', command_without_recurse)
            if m:
                path_arg = m.group(1).strip()
                # Handle comma-separated patterns like *.py,*.json -> use -Include
                if "," in path_arg:
                    # e.g., *.py,*.json,*.db -> Get-ChildItem -Path . -Recurse -File -Include *.py,*.json | Select-String
                    command = re.sub(
                        r'Select-String\s+-Path\s+[^\s;|]+',
                        f'Get-ChildItem -Path . -Recurse -File -Include {path_arg} | Select-String',
                        command_without_recurse,
                        count=1,
                    )
                else:
                    command = re.sub(
                        r'Select-String\s+-Path\s+[^\s;|]+',
                        f'Get-ChildItem -Path {path_arg} -Recurse -File | Select-String',
                        command_without_recurse,
                        count=1,
                    )
            else:
                # No explicit -Path, assume current directory
                command = command_without_recurse.replace(
                    "Select-String", "Get-ChildItem -Path . -Recurse -File | Select-String", 1
                )
        else:
            command = command_without_recurse

    # Fix common quoting hell for `python -c "..."` inside PowerShell
    # PowerShell's -Command parsing mangles nested quotes. If the command is a simple
    # `python -c "..."` with both single and double quotes, we will handle it via temp file
    # in execute() instead of fixing here. Just return.
    if command != original:
        # Log the rewrite for debugging (via print, but we don't have logger here)
        pass

    return command


def _is_python_c_command(command: str) -> tuple[bool, str]:
    """Detect `python -c "code"` and extract code. Returns (is_python_c, code)."""
    stripped = command.strip()
    # Match python or python3 or py, with -c
    m = re.match(r'^(?:python|python3|py)\s+-c\s+["\'](.*)["\']\s*$', stripped, re.DOTALL)
    if m:
        code = m.group(1)
        # PowerShell escapes inner double quotes as \" or `" and single as \' 
        code = code.replace('\\"', '"').replace('`"', '"').replace("\\'", "'").replace("''", "'")
        # Also handle the case where outer was " and inner ' was escaped as \'
        # e.g., 'data/nally.db' inside " becomes \'data/nally.db\' after PowerShell mangling
        return True, code
    # Also handle python -c without quotes but with code after (rare)
    m2 = re.match(r'^(?:python|python3|py)\s+-c\s+(.+)$', stripped, re.DOTALL)
    if m2 and ('import' in m2.group(1) or 'print' in m2.group(1)):
        # Probably code without proper quoting, but still python -c
        return True, m2.group(1).strip().strip('"').strip("'").replace('\\"', '"').replace("\\'", "'")
    return False, ""


def _get_shell():
    """Return (shell_executable, shell_args_prefix) for the current platform.

    Uses shutil.which to find the actual shell instead of hardcoded paths.
    On Windows, checks for pwsh (PowerShell 7) first, then Windows PowerShell,
    then falls back to cmd.exe.
    """
    if platform.system() == "Windows":
        # Try PowerShell 7 (pwsh) first, then Windows PowerShell, then cmd.exe
        for shell_name in ("pwsh", "powershell"):
            shell_path = shutil.which(shell_name)
            if shell_path:
                return shell_path, ["-NoProfile", "-NonInteractive", "-Command"]
        # Also check the env override before giving up
        powershell = os.environ.get("POWERSHELL_PATH", "")
        if powershell and os.path.exists(powershell):
            return powershell, ["-NoProfile", "-NonInteractive", "-Command"]
        return "cmd.exe", ["/c"]
    return "/bin/bash", ["-c"]


class RunCommand(Tool):
    def __init__(self):
        os_name = platform.system()
        shell_name = "PowerShell" if os_name == "Windows" else "bash"
        super().__init__(
            name="run_command",
            description=(
                f"Execute a {shell_name} command on this {os_name} system. Use for 'python file.py', 'python -c ...', 'bash script.sh', pip, pytest. Use {shell_name}-compatible syntax."
            ),
            permission="destructive",
            parameters={
                "command": {
                    "type": "string",
                    "description": f"The {shell_name} command to execute",
                    "required": True,
                }
            },
        )

    def execute(self, command: str = "") -> str:
        if not command:
            return "Error: No command provided"

        # Pre-process PowerShell quirks (&&, Select-String -Recurse)
        original_cmd = command
        if platform.system() == "Windows":
            command = _normalize_powershell(command)
            if command != original_cmd:
                # Keep original for debugging if needed, but execute normalized
                pass

        # Special handling for `python -c` to avoid PowerShell quoting hell
        # Example that previously failed: python -c "import sqlite3; c=sqlite3.connect('data/nally.db'); print(c.execute(\"SELECT ...\"))"
        # PowerShell mangles the nested quotes, so we extract the code and run via temp file
        is_py_c, py_code = _is_python_c_command(command.strip())
        if is_py_c and py_code:
            try:
                # Write to temp file to avoid any shell quoting
                with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as tf:
                    tf.write(py_code)
                    temp_path = tf.name
                try:
                    result = subprocess.run(
                        [sys.executable, temp_path],
                        capture_output=True,
                        encoding="utf-8",
                        errors="replace",
                        timeout=CMD_TIMEOUT,
                        cwd=str(Path.cwd()),
                    )
                    output = result.stdout
                    if result.stderr:
                        output += f"\nStderr: {result.stderr}"
                    if result.returncode != 0:
                        output += f"\nExit code: {result.returncode}"
                    return output if output else f"Command executed successfully (exit code: {result.returncode})"
                finally:
                    try:
                        Path(temp_path).unlink(missing_ok=True)
                    except Exception:
                        pass
            except Exception:
                # Fall through to normal shell execution if temp file approach fails
                pass

        # Handle combined `cd "path"; if ($?) { python -c "..." }` (from `cd "path" && python -c "..."`)
        if "; if ($?) {" in command and "python -c" in command:
            m_cd = re.search(r'cd\s+"([^"]+)"', command)
            m_py = re.search(r'python\s+-c\s+["\'](.*)["\']\s*\}*\s*$', command, re.DOTALL)
            if m_cd and m_py:
                cd_path = m_cd.group(1)
                py_code_inner = m_py.group(1).replace('\\"', '"').replace('`"', '"').replace("''", "'")
                try:
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as tf:
                        tf.write(py_code_inner)
                        temp_path2 = tf.name
                    try:
                        result = subprocess.run(
                            [sys.executable, temp_path2],
                            capture_output=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=CMD_TIMEOUT,
                            cwd=cd_path,
                        )
                        output = result.stdout
                        if result.stderr:
                            output += f"\nStderr: {result.stderr}"
                        if result.returncode != 0:
                            output += f"\nExit code: {result.returncode}"
                        return output if output else f"Command executed successfully (exit code: {result.returncode})"
                    finally:
                        try:
                            Path(temp_path2).unlink(missing_ok=True)
                        except Exception:
                            pass
                except Exception:
                    pass

        try:
            executable, args = _get_shell()
            result = subprocess.run(
                [executable] + args + [command],
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=CMD_TIMEOUT,
            )
            output = result.stdout
            if result.stderr:
                output += f"\nStderr: {result.stderr}"
            if result.returncode != 0:
                output += f"\nExit code: {result.returncode}"
            return output if output else f"Command executed successfully (exit code: {result.returncode})"
        except subprocess.TimeoutExpired:
            return f"Command timed out after {CMD_TIMEOUT} seconds"
        except Exception as e:
            return f"Error: {e!s}"


class SystemHealth(Tool):
    def __init__(self):
        super().__init__(
            name="system_health",
            description="Get system health (CPU, memory, disk usage)",
            parameters={},
        )

    def execute(self) -> str:
        try:
            import psutil

            cpu = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk_path = os.path.splitdrive(os.getcwd())[0] + os.sep if os.name == "nt" else "/"
            disk = psutil.disk_usage(disk_path)

            return (
                f"CPU: {cpu}% | "
                f"Memory: {memory.percent}% ({memory.used // (1024**3):.1f}GB / {memory.total // (1024**3):.1f}GB) | "
                f"Disk: {disk.percent}% ({disk.used // (1024**3):.1f}GB / {disk.total // (1024**3):.1f}GB)"
            )
        except ImportError:
            return "System health requires: pip install psutil"
        except Exception as e:
            return f"Error: {e!s}"
