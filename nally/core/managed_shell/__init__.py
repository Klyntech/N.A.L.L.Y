"""Nally Managed Shell — persistent PTY-like sessions (vibe port).

Provides TerminalSessionManager used internally by run_command(action=...).
The former shell_sessions / shell_output / shell_stdin tools were removed;
model-facing session access is via run_command session actions.
Behind NALLY_SHELL=legacy|managed flag (default legacy until stable).
"""

from .manager import ManagedShellManager, TerminalSession

__all__ = ["ManagedShellManager", "TerminalSession"]
