"""Memory data models — typed representations of stored data.

These are plain data classes, not ORM models.
The repository (store.py) handles persistence.
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class Memory:
    """A long-term fact with confidence scoring."""
    key: str
    value: str
    category: str = "general"
    confidence: float = 0.5
    mention_count: int = 1
    created: str = ""
    last_confirmed: str = ""
    deleted: bool = False
    id: Optional[int] = None

    @property
    def is_high_confidence(self) -> bool:
        return self.confidence >= 0.8

    @property
    def is_low_confidence(self) -> bool:
        return self.confidence < 0.5


@dataclass
class Episode:
    """A timestamped experience — what happened, outcome, solution."""
    topic: str
    what_happened: str
    outcome: str = ""
    solution: str = ""
    tags: List[str] = field(default_factory=list)
    date: str = ""
    created: str = ""
    id: Optional[int] = None


@dataclass
class ConversationSummary:
    """A summary of a past conversation session."""
    summary: str
    topics: List[str] = field(default_factory=list)
    start_date: str = ""
    end_date: str = ""
    message_count: int = 0
    created: str = ""
    id: Optional[int] = None


@dataclass
class SemanticPattern:
    """An extracted pattern or preference — strengthens with evidence."""
    pattern: str
    confidence: float = 0.5
    evidence_count: int = 1
    last_seen: str = ""
    created: str = ""
    id: Optional[int] = None
