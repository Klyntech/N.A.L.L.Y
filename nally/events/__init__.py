"""Event bus for decoupled pub-sub communication across NALLY components."""

from .bus import Event, EventBus, event_bus

__all__ = ["Event", "EventBus", "event_bus"]
