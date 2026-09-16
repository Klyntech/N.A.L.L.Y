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

# Foreground output cap — prevents OOM on `capture_output=True` with huge stdout/stderr.
# Mirrors managed-shell max_bytes (30k) but slightly larger for one-shot commands.
# 100k stdout + 30k stderr ≈ 130k chars ≈ ~130KB, safe for 512MB Render.
MAX_RUN_STDOUT = int(os.environ.get("NALLY_MAX_RUN_STDOUT", "100000"))
MAX_RUN_STDERR = int(os.environ.get("NALLY_MAX_RUN_STDERR", "30000"))


def _bounded_subprocess(cmd: list[str], cwd: str | None, timeout: int) -> tuple[str, str, int | None]:
    """Run cmd with file-backed stdout/stderr, truncated to MAX_RUN_*.

    Returns (stdout, stderr, returncode). On timeout returns (\"\", \"Error: ...\", 124).
    stdout/stderr are already decoded and truncated; never unbounded in memory.
    """
    # Use temp files so child output goes to disk, not PIPE buffers.
    out_fd, out_path = tempfile.mkstemp(prefix="nally-run-")
    err_fd, err_path = tempfile.mkstemp(prefix="nally-run-")
    os.close(out_fd)
    os.close(err_fd)
    try:
        with open(out_path, "wb") as out_f, open(err_path, "wb") as err_f:
            proc = subprocess.Popen(cmd, stdout=out_f, stderr=err_f, cwd=cwd)
            try:
                ret = proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                try:
                    proc.kill()
                    proc.wait(timeout=5)
                except Exception:
                    pass
                return "", f"Error: Command timed out after {timeout} seconds (exit code: 124)", 124

        def _read_capped(path: str, cap: int) -> str:
            try:
                size = os.path.getsize(path)
            except Exception:
                return ""
            try:
                with open(path, encoding="utf-8", errors="replace") as f:
                    data = f.read(cap + 1)
                if len(data) > cap:
                    return data[:cap] + f"\n... [truncated, {size} bytes on disk, showing {cap} chars]"
                return data
            except Exception as e:
                return f"Error reading output: {e}"

        stdout = _read_capped(out_path, MAX_RUN_STDOUT)
        stderr = _read_capped(err_path, MAX_RUN_STDERR)
        return stdout, stderr, ret
    finally:
        for p in (out_path, err_path):
            try:
                Path(p).unlink(missing_ok=True)
            except Exception:
                pass


def _normalize_powershell(command: str) -> str:
    """Fix common LLM-generated PowerShell mistakes before execution.

    - `A && B` -> `A; if ($?) { B }`  (PowerShell has no &&)
    - `Select-String -Path X -Recurse` -> `Get-ChildItem -Path X -Recurse -File | Select-String` (Select-String has no -Recurse)
    - Normalizes `;` handling
    """
    original = command

    # Fix && (bash) -> PowerShell ; if ($?) { ... }
    # Preserve quoted strings: don't split on " && " inside single/double quotes.
    # Simple state machine: track in_single / in_double / escaped.
    if " && " in command:
        parts = []
        cur = []
        _in_single = False
        _in_double = False
        _esc = False
        _i = 0
        while _i < len(command):
            ch = command[_i]
            if _esc:
                cur.append(ch)
                _esc = False
                _i += 1
                continue
            if ch == "\\" and not _in_single:
                _esc = True
                cur.append(ch)
                _i += 1
                continue
            if ch == "'" and not _in_double:
                _in_single = not _in_single
                cur.append(ch)
                _i += 1
                continue
            if ch == '"' and not _in_single:
                _in_double = not _in_double
                cur.append(ch)
                _i += 1
                continue
            if not _in_single and not _in_double and command[_i : _i + 4] == " && ":
                parts.append("".join(cur).strip())
                cur = []
                _i += 4
                continue
            cur.append(ch)
            _i += 1
        parts.append("".join(cur).strip())
        # Rebuild as properly nested if ($?) blocks: A; if ($?) { B; if ($?) { C } }
        # Each opened brace closed at end, not per part, so C only runs if B succeeded.
        normalized = parts[0]
        for part in parts[1:]:
            normalized += f"; if ($?) {{ {part.strip()}"
        normalized += " }" * (len(parts) - 1)
        command = normalized

    # Fix Select-String -Recurse (invalid) -> Get-ChildItem -Recurse | Select-String
    if "Select-String" in command and "-Recurse" in command:
        # Remove all standalone -Recurse flags (they belong to Get-ChildItem, not Select-String)
        command_without_recurse = re.sub(r"\s+-Recurse\b", "", command)
        # If Get-ChildItem not already present, inject it
        if "Get-ChildItem" not in command_without_recurse:
            # Handle `Select-String -Path <path>` -> `Get-ChildItem -Path <path> -Recurse -File | Select-String`
            m = re.search(r"Select-String\s+-Path\s+([^\s;|]+)", command_without_recurse)
            if m:
                path_arg = m.group(1).strip()
                # Handle comma-separated patterns like *.py,*.json -> use -Include
                if "," in path_arg:
                    # e.g., *.py,*.json,*.db -> Get-ChildItem -Path . -Recurse -File -Include *.py,*.json | Select-String
                    command = re.sub(
                        r"Select-String\s+-Path\s+[^\s;|]+",
                        f"Get-ChildItem -Path . -Recurse -File -Include {path_arg} | Select-String",
                        command_without_recurse,
                        count=1,
                    )
                else:
                    command = re.sub(
                        r"Select-String\s+-Path\s+[^\s;|]+",
                        f"Get-ChildItem -Path {path_arg} -Recurse -File | Select-String",
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
    """Detect `python -c "code"` and extract code. Returns (is_python_c, code).

    Handles quoted code correctly: scans for the matching closing quote
    that is not inside nested quotes of opposite type and not escaped.
    Avoids the previous `(.*)` greedy bug that captured until last " in
    `python -c "import json; print(\"hi\")"`.
    """
    stripped = command.strip()
    # Match prefix python -c plus opening quote
    m = re.match(r'^(?:python|python3|py)\s+-c\s+(["\'])', stripped)
    if m:
        q = m.group(1)
        # Find matching closing q that is not escaped and not inside opposite quotes
        rest = stripped[m.end() :]
        code_chars = []
        _esc = False
        _in_other = False
        _other_q = "'" if q == '"' else '"'
        for idx, ch in enumerate(rest):
            if _esc:
                code_chars.append(ch)
                _esc = False
                continue
            if ch == "\\" and not _in_other:
                _esc = True
                # keep escape for later unescape? drop it and keep char
                continue
            if ch == _other_q and q == '"':
                # toggle single inside double — not closing
                _in_other = not _in_other if ch == "'" else _in_other
                code_chars.append(ch)
                continue
            if ch == _other_q and q == "'":
                _in_other = not _in_other
                code_chars.append(ch)
                continue
            if ch == q and not _in_other and not _esc:
                # Closing quote — must be at end (allow trailing spaces/braces)
                suffix = rest[idx + 1 :].strip()
                # If suffix is only closing braces from PowerShell shim, ignore
                if suffix == "" or suffix.strip().rstrip("}").strip() == "":
                    code = "".join(code_chars)
                    code = code.replace('\\"', '"').replace('`"', '"').replace("\\'", "'").replace("''", "'")
                    return True, code
                # Otherwise this quote is inside code (escaped), keep going
                code_chars.append(ch)
                continue
            code_chars.append(ch)
        # No closing found — fallback to capturing all remaining
        code = rest.rstrip('"').rstrip("'")
        code = code.replace('\\"', '"').replace('`"', '"').replace("\\'", "'").replace("''", "'")
        if code:
            return True, code
    # Fallback: python -c without outer quotes
    m2 = re.match(r"^(?:python|python3|py)\s+-c\s+(.+)$", stripped, re.DOTALL)
    if m2 and ("import" in m2.group(1) or "print" in m2.group(1)):
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


# RunCommand removed — shell access / OOM hardening (see git history for prior impl)
# ManagedShellManager stays internal but no longer exposed as a tool.


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
