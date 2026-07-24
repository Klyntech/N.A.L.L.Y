"""System Control Tools"""
import os
import subprocess
from .registry import Tool, registry


class RunCommand(Tool):
    def __init__(self):
        super().__init__(
            name="run_command",
            description="Execute a shell command on the system",
            permission="destructive",
            parameters={
                "command": {
                    "type": "string",
                    "description": "The command to execute",
                    "required": True,
                }
            },
        )

    def execute(self, command: str) -> str:
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=30,
            )
            output = result.stdout
            if result.stderr:
                output += f"\nStderr: {result.stderr}"
            return output if output else "Command executed successfully"
        except subprocess.TimeoutExpired:
            return "Command timed out after 30 seconds"
        except Exception as e:
            return f"Error: {str(e)}"


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
            return f"Error: {str(e)}"
