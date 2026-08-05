"""Decoupled event bus for NALLY.

Components publish events without knowing who listens.
Subscribers register handlers without knowing who publishes.
Replaces hard-coded emit() threading with a single unified bus.
"""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("nally.events")

# ── Event Types ───────────────────────────────────────────

EVENT_TYPES = {
    # Agent events
    "thought",
    "stream_chunk",
    "stream_done",
    "tool_call",
    "tool_result",
    "response",
    "error",
    "done",
    # Planning events
    "plan_created",
    "plan_step_started",
    "plan_step_completed",
    "plan_revised",
    "plan_complete",
    # Reflection events
    "reflection_created",
    # System events
    "user_message",
    "assistant_message",
    "thinking",
    "history_cleared",
    "approval_resolved",
    "mcp_status",
    "confirmation_required",
    "busy",
    # Voice events
    "voice_transcript",
    "tts_audio",
}


@dataclass
class Event:
    """A single event published to the bus."""

    type: str
    data: Dict[str, Any]
    timestamp: float = field(default_factory=time.time)
    source: str = ""

    def to_dict(self) -> Dict[str, Any]:
        result = {"type": self.type}
        result.update(self.data)
        return result


# ── Event Bus ─────────────────────────────────────────────


class EventBus:
    """Thread-safe publish/subscribe event bus with history.

    Usage:
        # Publisher
        event_bus.publish("tool_call", {"name": "run_command", "args": {...}})

        # Subscriber
        def on_tool_call(event):
            print(f"Tool called: {event.data['name']}")

        event_bus.subscribe("tool_call", on_tool_call)
    """

    def __init__(self, history_size: int = 1000):
        self._handlers: Dict[str, List[Callable]] = {}
        self._wildcard_handlers: List[Callable] = []
        self._history: deque = deque(maxlen=history_size)
        self._lock = threading.Lock()
        self._stats: Dict[str, int] = {}

    def subscribe(self, event_type: str, handler: Callable) -> Callable:
        """Subscribe to an event type. Returns an unsubscribe callable."""
        with self._lock:
            if event_type == "*":
                self._wildcard_handlers.append(handler)
            else:
                if event_type not in self._handlers:
                    self._handlers[event_type] = []
                self._handlers[event_type].append(handler)
        logger.debug(f"Subscribed to '{event_type}': {handler.__qualname__}")

        def _unsubscribe():
            self.unsubscribe(event_type, handler)

        return _unsubscribe

    def unsubscribe(self, event_type: str, handler: Callable) -> None:
        """Remove a subscription."""
        with self._lock:
            if event_type == "*":
                self._wildcard_handlers = [h for h in self._wildcard_handlers if h != handler]
            elif event_type in self._handlers:
                self._handlers[event_type] = [h for h in self._handlers[event_type] if h != handler]

    def publish(self, event_type: str, data: Optional[Dict[str, Any]] = None, source: str = "") -> None:
        """Publish an event to all subscribers. Thread-safe, never blocks."""
        event = Event(type=event_type, data=data or {}, source=source)

        # Record history
        self._history.append(event)
        self._stats[event_type] = self._stats.get(event_type, 0) + 1

        # Get handlers under lock, then call outside lock
        with self._lock:
            handlers = list(self._handlers.get(event_type, []))
            wildcard = list(self._wildcard_handlers)

        for handler in handlers + wildcard:
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Event handler error ({event_type}): {e}")

    def get_history(self, event_type: Optional[str] = None, limit: int = 50) -> List[Event]:
        """Get recent events, optionally filtered by type."""
        events = list(self._history)
        if event_type:
            events = [e for e in events if e.type == event_type]
        return events[-limit:]

    def get_stats(self) -> Dict[str, int]:
        """Get event publish counts by type."""
        return dict(self._stats)

    def clear_history(self) -> None:
        """Clear event history."""
        self._history.clear()

    def handler_count(self, event_type: Optional[str] = None) -> int:
        """Count registered handlers."""
        with self._lock:
            if event_type:
                return len(self._handlers.get(event_type, []))
            return sum(len(h) for h in self._handlers.values()) + len(self._wildcard_handlers)


# ── Singleton ─────────────────────────────────────────────

event_bus = EventBus()
