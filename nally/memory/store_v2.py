"""Backward-compatible shim — imports from the new memory modules.

All new code should import from nally.memory.store or nally.memory directly.
This file exists only so that existing callers (core.py, context.py, tools/__init__.py)
don't break during the phased migration.
"""

from .store import MemoryRepository, MEMORY_TOOL_SCHEMAS
from . import memory_store as _memory_store
from . import memory_tools_v2 as _memory_tools_v2

# Backward-compatible singletons
memory_v2 = _memory_store
memory_tools_v2 = _memory_tools_v2

__all__ = ["memory_v2", "memory_tools_v2", "MemoryRepository"]
