"""Node-Level Caching — skip LLM calls on repeated similar inputs.

Caches node execution results so that repeated requests (like "what's on my
calendar today") don't waste LLM calls. Uses content hashing for cache keys.
"""

import hashlib
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional

logger = logging.getLogger("nally.cache")


@dataclass
class CacheEntry:
    """A single cached result."""
    key: str
    result: Any
    created_at: float
    ttl_seconds: int = 3600  # 1 hour default
    hit_count: int = 0

    @property
    def is_expired(self) -> bool:
        return time.time() - self.created_at > self.ttl_seconds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "created_at": self.created_at,
            "ttl_seconds": self.ttl_seconds,
            "hit_count": self.hit_count,
            "expired": self.is_expired,
        }


class NodeCache:
    """Cache for node execution results."""

    def __init__(self, max_size: int = 100, default_ttl: int = 3600):
        self._cache: Dict[str, CacheEntry] = {}
        self._max_size = max_size
        self._default_ttl = default_ttl
        self._stats = {"hits": 0, "misses": 0, "evictions": 0}

    def _make_key(self, node_name: str, inputs: Dict[str, Any]) -> str:
        """Create a cache key from node name and inputs."""
        # Hash the inputs for a stable key
        input_str = json.dumps(inputs, sort_keys=True, default=str)
        input_hash = hashlib.sha256(input_str.encode()).hexdigest()[:16]
        return f"{node_name}:{input_hash}"

    def get(self, node_name: str, inputs: Dict[str, Any]) -> Optional[Any]:
        """Get cached result if available and not expired."""
        key = self._make_key(node_name, inputs)
        entry = self._cache.get(key)

        if entry is None:
            self._stats["misses"] += 1
            return None

        if entry.is_expired:
            del self._cache[key]
            self._stats["misses"] += 1
            return None

        entry.hit_count += 1
        self._stats["hits"] += 1
        logger.debug(f"Cache hit: {node_name} (hit #{entry.hit_count})")
        return entry.result

    def set(self, node_name: str, inputs: Dict[str, Any], result: Any, ttl: Optional[int] = None):
        """Cache a result."""
        key = self._make_key(node_name, inputs)

        # Evict oldest if at capacity
        if len(self._cache) >= self._max_size and key not in self._cache:
            oldest_key = min(self._cache, key=lambda k: self._cache[k].created_at)
            del self._cache[oldest_key]
            self._stats["evictions"] += 1

        self._cache[key] = CacheEntry(
            key=key,
            result=result,
            created_at=time.time(),
            ttl_seconds=ttl or self._default_ttl,
        )

    def invalidate(self, node_name: str):
        """Invalidate all entries for a node."""
        keys_to_remove = [k for k in self._cache if k.startswith(f"{node_name}:")]
        for key in keys_to_remove:
            del self._cache[key]

    def clear(self):
        """Clear all cached entries."""
        self._cache.clear()

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total = self._stats["hits"] + self._stats["misses"]
        return {
            **self._stats,
            "size": len(self._cache),
            "hit_rate": self._stats["hits"] / total if total > 0 else 0,
        }


def cached_node(node_name: str, ttl: int = 3600):
    """Decorator that caches a graph node's execution result.

    Usage:
        @cached_node("calendar_fetch", ttl=300)
        def fetch_calendar(state):
            # ... expensive operation ...
            return {"calendar": events}
    """
    def decorator(func: Callable) -> Callable:
        def wrapper(state: Dict[str, Any]) -> Dict[str, Any]:
            # Extract cacheable inputs from state
            inputs = {
                "messages_count": len(state.get("messages", [])),
                "iteration": state.get("iteration", 0),
                "intent_class": state.get("intent_class", ""),
            }

            # Check cache
            result = _node_cache.get(node_name, inputs)
            if result is not None:
                return result

            # Execute and cache
            result = func(state)
            _node_cache.set(node_name, inputs, result, ttl)
            return result

        wrapper._cache_node_name = node_name
        return wrapper
    return decorator


# Singleton
_node_cache = NodeCache()
