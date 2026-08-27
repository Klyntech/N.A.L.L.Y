"""Nally Managed Shell — persistent PTY-like sessions (vibe port).

Provides TerminalSessionManager used by Phase 2 tools:
  shell_sessions / shell_output / shell_stdin
Behind NALLY_SHELL=legacy|managed flag (default legacy until stable).
"""

from .manager import ManagedShellManager, TerminalSession

__all__ = ["ManagedShellManager", "TerminalSession"]
