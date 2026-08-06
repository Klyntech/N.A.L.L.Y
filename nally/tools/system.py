"""System Control Tools"""

import os
import platform
import subprocess

from .registry import Tool

# Command timeout (seconds) — configurable via env
CMD_TIMEOUT = int(os.environ.get("NALLY_CMD_TIMEOUT", "60"))


def _get_shell():
    """Return (shell_executable, shell_args_prefix) for the current platform."""
    if platform.system() == "Windows":
        powershell = os.environ.get(
            "POWERSHELL_PATH",
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        )
        if os.path.exists(powershell):
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
                f"Execute a {shell_name} command on this {os_name} system. Use {shell_name}-compatible syntax."
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
