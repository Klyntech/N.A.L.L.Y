"""Semantic Memory — weighted recall by similarity, recency, and importance.

Pattern from CrewAI: memory ranked by composite score of semantic similarity,
recency, and importance — not just vector distance. Better recall of recent,
important personal context.
"""

import logging
import math
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nally.semantic_memory")

# Simple stopwords for keyword extraction
_STOPWORDS = frozenset({
    "the", "is", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for",
    "of", "with", "by", "from", "it", "this", "that", "are", "was", "were", "be",
    "have", "has", "had", "do", "does", "did", "will", "would", "could", "should",
    "may", "might", "can", "shall", "not", "no", "if", "then", "than", "so",
    "just", "about", "what", "when", "where", "how", "who", "which", "there",
    "here", "now", "also", "very", "too", "my", "your", "its", "our", "their",
    "me", "him", "her", "us", "them", "you", "he", "she", "we", "they", "i",
})


@dataclass
class MemoryEntry:
    """A memory entry with metadata for scoring."""
    key: str
    value: str
    category: str
    confidence: float
    created_at: float
    last_accessed: float
    mention_count: int = 1
    importance: float = 0.5  # 0.0 = trivial, 1.0 = critical

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "value": self.value,
            "category": self.category,
            "confidence": self.confidence,
            "importance": self.importance,
            "mention_count": self.mention_count,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
        }


class SemanticMemoryEngine:
    """Memory engine with composite scoring: similarity + recency + importance."""

    def __init__(self):
        self._memories: List[MemoryEntry] = []
        self._category_weights = {
            "project": 1.2,   # Projects are important
            "auto_fact": 1.0,
            "fact": 1.0,
            "episode": 0.8,
            "general": 0.5,
        }
        # Importance keywords boost importance score
        self._importance_keywords = {
            "high": ["password", "secret", "api", "token", "credential", "important",
                     "critical", "urgent", "deadline", "payment", "invoice"],
            "medium": ["project", "meeting", "appointment", "task", "todo", "goal"],
            "low": ["weather", "joke", "random", "fun", "entertainment"],
        }

    def add(self, key: str, value: str, category: str = "general",
            confidence: float = 0.5, importance: float = None):
        """Add or update a memory entry."""
        now = time.time()

        # Auto-compute importance if not provided
        if importance is None:
            importance = self._compute_importance(key, value, category)

        # Check if memory already exists (update)
        for mem in self._memories:
            if mem.key == key:
                mem.value = value
                mem.category = category
                mem.confidence = confidence
                mem.importance = importance
                mem.last_accessed = now
                mem.mention_count += 1
                return

        self._memories.append(MemoryEntry(
            key=key,
            value=value,
            category=category,
            confidence=confidence,
            created_at=now,
            last_accessed=now,
            importance=importance,
        ))

    def recall(self, query: str, limit: int = 12, min_confidence: float = 0.3) -> List[MemoryEntry]:
        """Recall memories ranked by composite score.

        Score = w_sim * similarity + w_rec * recency + w_imp * importance + w_con * confidence
        """
        if not self._memories:
            return []

        query_tokens = self._tokenize(query)
        now = time.time()
        scored = []

        for mem in self._memories:
            if mem.confidence < min_confidence:
                continue

            # Similarity: keyword overlap
            mem_tokens = self._tokenize(f"{mem.key} {mem.value}")
            if query_tokens and mem_tokens:
                overlap = len(query_tokens & mem_tokens)
                similarity = min(overlap / max(len(query_tokens), 1), 1.0)
            else:
                similarity = 0.0

            # Recency: exponential decay (half-life = 7 days)
            age_days = (now - mem.last_accessed) / 86400
            recency = math.exp(-0.1 * age_days)

            # Importance: direct score
            importance = mem.importance

            # Confidence: direct score
            confidence = mem.confidence

            # Category weight
            cat_weight = self._category_weights.get(mem.category, 0.5)

            # Composite score (weighted)
            score = (
                0.35 * similarity +
                0.25 * recency +
                0.25 * importance +
                0.15 * confidence
            ) * cat_weight

            scored.append((mem, score))

        # Sort by score descending
        scored.sort(key=lambda x: x[1], reverse=True)

        # Update last_accessed for recalled memories
        result = []
        for mem, score in scored[:limit]:
            mem.last_accessed = now
            result.append(mem)

        return result

    def _compute_importance(self, key: str, value: str, category: str) -> float:
        """Auto-compute importance based on content and category."""
        text = f"{key} {value}".lower()

        # Check importance keywords
        high_matches = sum(1 for kw in self._importance_keywords["high"] if kw in text)
        medium_matches = sum(1 for kw in self._importance_keywords["medium"] if kw in text)
        low_matches = sum(1 for kw in self._importance_keywords["low"] if kw in text)

        if high_matches > 0:
            importance = min(0.8 + high_matches * 0.05, 1.0)
        elif medium_matches > 0:
            importance = min(0.5 + medium_matches * 0.05, 0.8)
        elif low_matches > 0:
            importance = max(0.2 - low_matches * 0.05, 0.0)
        else:
            importance = 0.5

        # Category boost
        cat_boost = self._category_weights.get(category, 0.5) - 0.5
        importance = max(0.0, min(1.0, importance + cat_boost))

        return importance

    def _tokenize(self, text: str) -> set:
        """Tokenize text into meaningful tokens."""
        return {
            t for t in re.split(r"[^a-z0-9]+", text.lower())
            if len(t) > 2 and t not in _STOPWORDS
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics."""
        categories = {}
        for mem in self._memories:
            categories[mem.category] = categories.get(mem.category, 0) + 1
        return {
            "total_memories": len(self._memories),
            "categories": categories,
            "avg_importance": sum(m.importance for m in self._memories) / max(len(self._memories), 1),
            "avg_confidence": sum(m.confidence for m in self._memories) / max(len(self._memories), 1),
        }


# Singleton
semantic_memory = SemanticMemoryEngine()
