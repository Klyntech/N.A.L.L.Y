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
    """Derive the chat interface label from the session id or channel label.

    Legacy session-id prefixes are still recognized for backward compat;
    new code passes an explicit human label instead (see agent/identity.py).
    """
    if not session_id:
        return "CLI"
    for prefix, label in (
        ("web:", "Web"),
        ("telegram:", "Telegram"),
        ("tg_user:", "Telegram user account"),
        ("tg_voice:", "Telegram voice call"),
        ("group:", "Telegram group"),
        ("user:", None),  # shared owner session — label comes from caller
        ("voice:", "Voice"),
        ("voip:", "VoIP"),
    ):
        if session_id.startswith(prefix):
            return label or "Shared session"
    return "CLI"


def format_interface_context(interface: str) -> str:
    """Return a short line identifying the interaction channel.

    Accepts either a raw human label (preferred — passed via SessionRef.channel)
    or a legacy session id whose prefix is sniffed.
    """
    if interface and ":" in interface:
        label = detect_interface(interface)
    else:
        label = interface or "CLI"
    return f"Interaction channel: {label}"
