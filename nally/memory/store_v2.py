"""Backward-compatible shim — imports from the new memory modules.

All new code should import from nally.memory.store or nally.memory directly.
This file exists only so that existing callers (core.py, context.py, tools/__init__.py)
don't break during the phased migration.
"""

from . import memory_store as _memory_store
from . import memory_tools_v2 as _memory_tools_v2

# Deprecation notice — emitted lazily to avoid import-time hangs.
# Use: python -W always::DeprecationWarning to surface.
def _warn_deprecated():
    import warnings

    warnings.warn(
        "nally.memory.store_v2 is deprecated — use 'from nally.memory import memory_store'",
        DeprecationWarning,
        stacklevel=3,
    )
from .store import MemoryRepository

# Backward-compatible singletons
memory_v2 = _memory_store
memory_tools_v2 = _memory_tools_v2

__all__ = ["MemoryRepository", "memory_tools_v2", "memory_v2"]
