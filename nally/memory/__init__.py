"""Nally Memory System — repository pattern with confidence scoring.

Exports:
    memory_store: MemoryRepository instance (the new interface)
    memory_v2: Alias for backward compatibility
    memory_tools_v2: MemoryToolsV2 instance for tool registration
    MemoryRepository: The repository class
"""

from .store import MemoryRepository, MEMORY_TOOL_SCHEMAS
from .models import Memory, Episode, ConversationSummary, SemanticPattern
from .confidence import decay_confidence, boost_confidence

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
    "memory_store",
    "memory_v2",
    "memory_tools_v2",
    "MemoryRepository",
    "MemoryToolsV2",
    "Memory",
    "Episode",
    "ConversationSummary",
    "SemanticPattern",
    "user_profile",
]
