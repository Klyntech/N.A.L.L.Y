"""Confidence scoring — pure functions for memory confidence management.

Extracted from the store to keep scoring logic testable and decoupled from persistence.
"""

from datetime import datetime


def decay_confidence(days_since_confirmed: float) -> float:
    """Calculate confidence decay factor based on time since last confirmation.

    Returns a multiplier (0.0-1.0) to apply to the current confidence.
    Recent memories保持 their full confidence; old ones decay.
    """
    if days_since_confirmed < 7:
        return 1.0  # No decay for recent memories
    elif days_since_confirmed < 30:
        return 0.9  # Slight decay
    elif days_since_confirmed < 90:
        return 0.7  # Moderate decay
    elif days_since_confirmed < 180:
        return 0.5  # Significant decay
    else:
        return 0.3  # Heavy decay — memory is fading


def boost_confidence(current: float, amount: float = 0.1, maximum: float = 1.0) -> float:
    """Boost confidence by a fixed amount, capped at maximum."""
    return min(maximum, current + amount)


def days_since(iso_timestamp: str) -> float:
    """Calculate days between an ISO timestamp and now."""
    try:
        then = datetime.fromisoformat(iso_timestamp)
        delta = datetime.now() - then
        return delta.total_seconds() / 86400
    except (ValueError, TypeError):
        return 0.0


def initial_confidence() -> float:
    """Starting confidence for a new memory."""
    return 0.5
