"""Nally Memory System — repository pattern with confidence scoring.

Exports:
    memory_store: MemoryRepository instance (canonical)
    MemoryRepository: The repository class
    MemoryToolsV2: Schema provider for memory tool registration
"""

from .confidence import boost_confidence, decay_confidence
from .models import ConversationSummary, Episode, Memory, SemanticPattern
from .store import MEMORY_TOOL_SCHEMAS, MemoryRepository

# Singleton repository (canonical)
memory_store = MemoryRepository()


class MemoryToolsV2:
    """Provides OpenAI function schemas for memory tools."""

    def __init__(self, store: MemoryRepository):
        self.store = store

    def to_tool_list(self) -> list:
        return MEMORY_TOOL_SCHEMAS


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
    "user_profile",
]
