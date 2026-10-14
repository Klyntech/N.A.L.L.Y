"""Tools for interacting with persistent managed shell sessions."""

from __future__ import annotations

from ..core.managed_shell.manager import get_manager
from .registry import Tool


class ShellSessions(Tool):
    """List, inspect, or terminate managed shell sessions."""

    def __init__(self):
        super().__init__(
            name="shell_sessions",
            description="List managed shell sessions or inspect/kill a session.",
            permission="destructive",
            parameters={
                "action": {"type": "string", "enum": ["list", "inspect", "kill"], "default": "list"},
                "session_id": {"type": "string", "description": "Session ID for inspect or kill."},
            },
        )

    def execute(self, action: str = "list", session_id: str = "", **kwargs) -> str:
        manager = get_manager()
        try:
            if action == "list":
                sessions = manager.list_sessions()
                if not sessions:
                    return "No managed shell sessions."
                return "\n".join(
                    f"{item.get('session_id', '?')} [{item.get('status', 'unknown')}] "
                    f"{item.get('command', '')}"
                    for item in sessions
                )
            if not session_id:
                return "Error: session_id is required for inspect/kill."
            if action == "inspect":
                info = manager.inspect(session_id)
                return f"Session: {info['session']}\nOutput:\n{info['tail']}"
            if action == "kill":
                return "Session terminated." if manager.kill(session_id) else "Session was not running."
            return f"Error: unsupported action '{action}'."
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            return f"Error: {exc}"


class ShellOutput(Tool):
    """Read output from a managed shell session."""

    def __init__(self):
        super().__init__(
            name="shell_output",
            description="Read newly produced output from a managed shell session using a byte cursor.",
            permission="safe",
            parameters={
                "session_id": {"type": "string", "description": "Managed shell session ID.", "required": True},
                "cursor": {"type": "integer", "description": "Byte offset to read from.", "default": 0},
                "max_bytes": {"type": "integer", "description": "Maximum bytes to return.", "default": 30000},
                "wait_seconds": {"type": "number", "description": "How long to wait for output.", "default": 0.2},
            },
        )

    def execute(
        self, session_id: str, cursor: int = 0, max_bytes: int = 30000, wait_seconds: float = 0.2, **kwargs
    ) -> str:
        try:
            session, data, next_cursor = get_manager().read_output(
                session_id, cursor=cursor, max_bytes=max(1, min(max_bytes, 50000)), wait_seconds=max(0, wait_seconds)
            )
            output = data.decode("utf-8", errors="replace")
            return f"Session: {session.session_id} [{session.status}]\nCursor: {next_cursor}\n{output}"
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            return f"Error: {exc}"


class ShellStdin(Tool):
    """Send input to a running managed shell session."""

    def __init__(self):
        super().__init__(
            name="shell_stdin",
            description="Send a line of text to a running managed shell session.",
            permission="destructive",
            parameters={
                "session_id": {"type": "string", "description": "Managed shell session ID.", "required": True},
                "text": {"type": "string", "description": "Text to send to the session stdin.", "required": True},
            },
        )

    def execute(self, session_id: str, text: str, **kwargs) -> str:
        try:
            get_manager().write_stdin(session_id, text)
            return f"Input sent to session {session_id}."
        except (FileNotFoundError, RuntimeError, ValueError) as exc:
            return f"Error: {exc}"
