"""Nally Hooks — deterministic automation (vibe/Claude port).

PreToolUse can block, PostToolUse can mutate additionalContext.
Config: nally/config/hooks.json (JSON, merge with permissions.json semantics)
"""

from .manager import HookManager, get_hook_manager
from .models import HookConfig, HookEvent

__all__ = ["HookManager", "get_hook_manager", "HookConfig", "HookEvent"]
