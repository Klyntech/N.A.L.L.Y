"""Managed shell tools — shell_sessions / shell_output / shell_stdin.

Vibe-style quadruple for persistent sessions (Phase 2).
Tools are registered alongside run_command; run_command stays for one-shot.
"""

from typing import Optional

from .registry import Tool


class ShellSessions(Tool):
    def __init__(self):
        super().__init__(
            name="shell_sessions",
            description="List/inspect/kill managed shell sessions (persistent background shells). Use for long-running commands that outlive one tool call.",
            parameters={
                "action": {
                    "type": "string",
                    "enum": ["list", "inspect", "kill"],
                    "description": "list = all sessions, inspect = tail + metadata, kill = stop session",
                    "required": True,
                },
                "session_id": {"type": "string", "description": "Session ID for inspect/kill"},
                "max_bytes": {"type": "integer", "description": "Max bytes for inspect tail (default 10000)"},
            },
        )

    def execute(self, action: str = "list", session_id: str = "", max_bytes: int = 10000, **kwargs) -> str:
        from nally.core.managed_shell.manager import get_manager

        mgr = get_manager()
        try:
            if action == "list":
                sessions = mgr.list_sessions()
                if not sessions:
                    return "No managed shell sessions."
                lines = []
                for s in sessions[:20]:
                    lines.append(f"{s['session_id']} [{s['status']}] pid={s.get('pid')} cmd={s['command'][:60]} cwd={s['cwd']}")
                return "\n".join(lines)
            elif action == "inspect":
                if not session_id:
                    return "Error: session_id required for inspect"
                info = mgr.inspect(session_id, max_bytes=max_bytes)
                sess = info["session"]
                return f"Session {sess['session_id']} [{sess['status']}] exit={sess.get('exit_code')}\nCommand: {sess['command']}\nCwd: {sess['cwd']}\n--- tail ---\n{info['tail']}"
            elif action == "kill":
                if not session_id:
                    return "Error: session_id required for kill"
                ok = mgr.kill(session_id)
                return f"Killed {session_id}" if ok else f"Session {session_id} not running or not found"
            else:
                return f"Error: Unknown action {action}"
        except FileNotFoundError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"


class ShellOutput(Tool):
    def __init__(self):
        super().__init__(
            name="shell_output",
            description="Read output from a managed shell session (paged by cursor). Use after starting a background shell to poll its log.",
            parameters={
                "session_id": {"type": "string", "description": "Session ID", "required": True},
                "cursor": {"type": "integer", "description": "Byte offset to read from (next_cursor from previous call)"},
                "max_bytes": {"type": "integer", "description": "Max bytes to return (default 30000)"},
                "wait_seconds": {"type": "number", "description": "Wait for fresh output if at EOF and still running (default 0.5)"},
            },
        )

    def execute(
        self,
        session_id: str = "",
        cursor: int = 0,
        max_bytes: int = 30000,
        wait_seconds: float = 0.5,
        **kwargs,
    ) -> str:
        if not session_id:
            return "Error: session_id required"
        from nally.core.managed_shell.manager import get_manager

        mgr = get_manager()
        try:
            sess, data, next_cursor = mgr.read_output(session_id, cursor=cursor, max_bytes=max_bytes, wait_seconds=wait_seconds)
            text = data.decode("utf-8", errors="replace")
            header = f"[{sess.status}] session={sess.session_id} cursor={cursor} -> {next_cursor} (status={sess.status} exit={sess.exit_code})"
            if not text:
                text = "(no new output)"
            # Cap text to avoid truncation cascade but keep plenty
            if len(text) > 30000:
                text = text[:30000] + f"\n... [{len(text)} chars truncated]"
            return header + "\n" + text + f"\n-- next_cursor: {next_cursor} --"
        except FileNotFoundError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"


class ShellStdin(Tool):
    def __init__(self):
        super().__init__(
            name="shell_stdin",
            description="Send input to a managed shell session's stdin (for REPLs, prompts).",
            parameters={
                "session_id": {"type": "string", "description": "Session ID", "required": True},
                "text": {"type": "string", "description": "Text to send (newline appended if missing)", "required": True},
            },
        )

    def execute(self, session_id: str = "", text: str = "", **kwargs) -> str:
        if not session_id:
            return "Error: session_id required"
        if text is None:
            return "Error: text required"
        # Alias: some models send 'command' or 'input'
        if not text:
            text = kwargs.get("command", "") or kwargs.get("input", "")
            if not text:
                return "Error: text (or command/input) required"
        from nally.core.managed_shell.manager import get_manager

        mgr = get_manager()
        try:
            mgr.write_stdin(session_id, text)
            return f"Sent {len(text)} chars to {session_id}"
        except FileNotFoundError as e:
            return f"Error: {e}"
        except RuntimeError as e:
            return f"Error: {e}"
        except Exception as e:
            return f"Error: {type(e).__name__}: {e}"


def register_managed_shell_tools(registry):
    """Register shell_* tools if managed shell is enabled."""
    import os

    # Behind flag NALLY_SHELL=managed or NALLY_MANAGED_SHELL=1 (default: always register but gate execution)
    # For Phase 2 we always register so discovery works; gate is inside manager if needed.
    registry.register(ShellSessions())
    registry.register(ShellOutput())
    registry.register(ShellStdin())
