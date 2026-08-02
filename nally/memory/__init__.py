"""Nally Memory System — repository pattern with confidence scoring.

Exports:
    memory_store: MemoryRepository instance (the new interface)
    memory_v2: Alias for backward compatibility
    memory_tools_v2: MemoryToolsV2 instance for tool registration
    MemoryRepository: The repository class
"""

from .confidence import boost_confidence, decay_confidence
from .models import ConversationSummary, Episode, Memory, SemanticPattern
from .store import MEMORY_TOOL_SCHEMAS, MemoryRepository

# Singleton repository
memory_store = MemoryRepository()

# Backward-compatible aliases
memory_v2 = memory_store


class MemoryToolsV2:
    """Provides OpenAI function schemas for memory tools."""

    def __init__(self, store: MemoryRepository):
        self.store = store

    def to_tool_list(self) -> list:
        return MEMORY_TOOL_SCHEMAS


memory_tools_v2 = MemoryToolsV2(memory_store)

# Try to load user profile (may not exist)
try:
    from .profile import user_profile
except ImportError:
    user_profile = None

__all__ = [
    "ConversationSummary",
    "Episode",
    "Memory",
    "MemoryRepository",
    "MemoryToolsV2",
    "SemanticPattern",
    "boost_confidence",
    "decay_confidence",
    "memory_store",
    "memory_tools_v2",
    "memory_v2",
    "user_profile",
]
