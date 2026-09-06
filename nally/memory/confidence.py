"""Confidence scoring — pure functions for memory confidence management.

Extracted from the store to keep scoring logic testable and decoupled from persistence.
"""

import logging
from datetime import datetime

logger = logging.getLogger("nally.memory.confidence")


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


def days_since(timestamp) -> float:
    """Days between a timestamp and now.

    Canonical contract: ISO-8601 strings (as written by MemoryRepository).
    Also accepted (defensively, for legacy/external rows): unix epoch
    int/float (or numeric strings) and datetime objects.
    None/empty means "no age info" and yields 0.0 (no decay).
    Unparseable non-empty values yield 0.0 WITH a warning — never silent,
    and never treated as ancient (which would nuke confidence on corrupt
    data) nor as fresh-by-policy. Callers needing strictness should
    validate before storing.
    """
    if timestamp is None:
        return 0.0
    if isinstance(timestamp, datetime):
        then = timestamp
    elif isinstance(timestamp, (int, float)):
        try:
            then = datetime.fromtimestamp(timestamp)
        except (ValueError, OSError, OverflowError):
            logger.warning(f"Unparseable memory timestamp: {timestamp!r}")
            return 0.0
    elif isinstance(timestamp, str):
        text = timestamp.strip()
        if not text:
            return 0.0
        try:
            then = datetime.fromisoformat(text)
        except ValueError:
            try:
                then = datetime.fromtimestamp(float(text))
            except (ValueError, OSError, OverflowError):
                logger.warning(f"Unparseable memory timestamp: {timestamp!r}")
                return 0.0
    else:
        logger.warning(f"Unparseable memory timestamp of type {type(timestamp).__name__}")
        return 0.0
    try:
        delta = datetime.now() - then
        return max(0.0, delta.total_seconds() / 86400)
    except Exception:
        logger.warning(f"Unparseable memory timestamp: {timestamp!r}")
        return 0.0
