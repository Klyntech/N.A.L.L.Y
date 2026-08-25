"""Pub/Sub Message Pool — topic-based agent communication.

Pattern from MetaGPT/AutoGen: agents subscribe to topics and communicate
through a shared message bus. Decouples agents from each other — adding
new capabilities means subscribing to a topic, not modifying core logic.
"""

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("nally.pubsub")


@dataclass
class Message:
    """A message published to a topic."""
    topic: str
    data: Dict[str, Any]
    publisher: str
    timestamp: float = field(default_factory=time.time)
    message_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "topic": self.topic,
            "data": self.data,
            "publisher": self.publisher,
            "timestamp": self.timestamp,
            "message_id": self.message_id,
        }


@dataclass
class Subscription:
    """A subscription to a topic."""
    subscriber_id: str
    topic_pattern: str  # Can be exact match or regex pattern
    callback: Callable
    once: bool = False  # Auto-unsubscribe after first message

    def matches(self, topic: str) -> bool:
        """Check if this subscription matches a topic."""
        if self.topic_pattern == "*":
            return True
        if self.topic_pattern == topic:
            return True
        try:
            return bool(re.match(self.topic_pattern, topic))
        except re.error:
            return self.topic_pattern == topic


class PubSubBus:
    """Topic-based publish-subscribe message bus."""

    def __init__(self):
        self._subscriptions: Dict[str, List[Subscription]] = {}
        self._history: List[Message] = []
        self._lock = threading.Lock()
        self._max_history = 1000
        self._stats = {"published": 0, "delivered": 0}

    def subscribe(self, subscriber_id: str, topic_pattern: str, callback: Callable, once: bool = False) -> str:
        """Subscribe to a topic pattern. Returns subscription ID."""
        with self._lock:
            if topic_pattern not in self._subscriptions:
                self._subscriptions[topic_pattern] = []

            sub = Subscription(
                subscriber_id=subscriber_id,
                topic_pattern=topic_pattern,
                callback=callback,
                once=once,
            )
            self._subscriptions[topic_pattern].append(sub)
            logger.debug(f"Subscription: {subscriber_id} → {topic_pattern}")
            return f"{subscriber_id}:{topic_pattern}"

    def unsubscribe(self, subscriber_id: str, topic_pattern: str):
        """Remove a subscription."""
        with self._lock:
            if topic_pattern in self._subscriptions:
                self._subscriptions[topic_pattern] = [
                    s for s in self._subscriptions[topic_pattern]
                    if s.subscriber_id != subscriber_id
                ]

    def publish(self, topic: str, data: Dict[str, Any], publisher: str = "system"):
        """Publish a message to a topic."""
        msg = Message(topic=topic, data=data, publisher=publisher)

        with self._lock:
            self._history.append(msg)
            if len(self._history) > self._max_history:
                self._history = self._history[-self._max_history:]

        self._stats["published"] += 1

        # Deliver to matching subscribers
        delivered = 0
        once_subs = []
        with self._lock:
            for pattern, subs in self._subscriptions.items():
                for sub in subs:
                    if sub.matches(topic):
                        try:
                            sub.callback(msg)
                            delivered += 1
                            if sub.once:
                                once_subs.append((pattern, sub))
                        except Exception as e:
                            logger.warning(f"Subscription callback failed: {e}")

        # Remove one-time subscriptions
        for pattern, sub in once_subs:
            with self._lock:
                if pattern in self._subscriptions:
                    self._subscriptions[pattern] = [
                        s for s in self._subscriptions[pattern]
                        if s.subscriber_id != sub.subscriber_id
                    ]

        self._stats["delivered"] += delivered

    def get_history(self, topic: Optional[str] = None, limit: int = 50) -> List[Dict]:
        """Get message history, optionally filtered by topic."""
        with self._lock:
            msgs = self._history
            if topic:
                msgs = [m for m in msgs if m.topic == topic]
            return [m.to_dict() for m in msgs[-limit:]]

    def get_subscribers(self, topic: Optional[str] = None) -> List[Dict]:
        """Get all subscribers, optionally filtered by topic."""
        with self._lock:
            result = []
            for pattern, subs in self._subscriptions.items():
                if topic and pattern != topic and not re.match(pattern, topic):
                    continue
                for sub in subs:
                    result.append({
                        "subscriber": sub.subscriber_id,
                        "topic_pattern": sub.topic_pattern,
                        "once": sub.once,
                    })
            return result

    def get_stats(self) -> Dict[str, Any]:
        """Get bus statistics."""
        with self._lock:
            return {
                **self._stats,
                "subscriptions": sum(len(s) for s in self._subscriptions.values()),
                "topics": len(self._subscriptions),
                "history_size": len(self._history),
            }


# Singleton
pubsub = PubSubBus()
