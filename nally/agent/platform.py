"""Platform detection — single source of truth for OS, arch, shell info.

Injected into the LLM system prompt so it always knows what system
it's running on and generates correct commands.
"""

import os
import platform
import shutil


def get_platform_info() -> dict:
    """Return OS, architecture, shell, and key tool availability."""
    system = platform.system()  # "Windows", "Linux", "Darwin"
    release = platform.release()
    machine = platform.machine()
    python_ver = platform.python_version()

    if system == "Windows":
        # Prefer PowerShell if available (modern Windows default)
        powershell = os.environ.get(
            "POWERSHELL_PATH",
            r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
        )
        if os.path.exists(powershell):
            shell = powershell
            shell_name = "PowerShell"
        else:
            shell = os.environ.get("COMSPEC", "cmd.exe")
            shell_name = "cmd"
    else:
        shell = os.environ.get("SHELL", "/bin/bash")
        shell_name = os.path.basename(shell)

    tools = {}
    for cmd in ["git", "node", "python", "pip", "docker", "npm", "curl"]:
        tools[cmd] = shutil.which(cmd) is not None

    return {
        "os": system,
        "os_version": release,
        "arch": machine,
        "python": python_ver,
        "shell": shell,
        "shell_name": shell_name,
        "cwd": os.getcwd(),
        "tools": tools,
    }


def format_platform_context() -> str:
    """Format platform info as a one-line context string for the system prompt."""
    info = get_platform_info()
    tool_names = [t for t, avail in info["tools"].items() if avail]
    tool_str = ", ".join(tool_names) if tool_names else "none detected"

    return (
        f"SYSTEM INFO: {info['os']} {info['os_version']} ({info['arch']}) | "
        f"Shell: {info['shell_name']} | Python: {info['python']} | "
        f"Working dir: {info['cwd']} | "
        f"Available tools: {tool_str}\n"
        f"Use {info['shell_name']}-compatible commands. "
        f"On Windows use PowerShell syntax (not bash). "
        f"On macOS/Linux use bash syntax."
    )


def detect_interface(session_id: str) -> str:
    """Derive the chat interface label from the session ID."""
    if session_id.startswith("web:"):
        return "Web"
    if session_id.startswith("telegram:"):
        return "Telegram"
    if session_id.startswith("voice:"):
        return "Voice"
    if session_id.startswith("voip:"):
        return "VoIP"
    return "CLI"


def format_interface_context(session_id: str) -> str:
    """Return a short line identifying the interaction channel."""
    return f"Interaction channel: {detect_interface(session_id)}"
