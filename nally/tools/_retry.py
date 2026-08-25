"""Shared retry utility for transient failures with exponential backoff.

Usage:
    from ._retry import retry_transient

    result = retry_transient(lambda: httpx.get(url, timeout=10))

Tools wrap their external API calls in this helper to get automatic retries
on 5xx, 429, timeouts, and connection errors without duplicating logic.
"""

import logging
import time
from typing import Any, Callable, Optional, Tuple

logger = logging.getLogger("nally.tools.retry")

# Error substrings that indicate a transient (retryable) failure.
# Matches the same hints used in nally/agent/graph.py for consistency.
TRANSIENT_HINTS = (
    "timeout", "timed out", "429", "503", "502", "500",
    "temporarily", "connection reset", "try again", "rate limit",
    "overloaded", "socket", "econn", "temporary failure", "gateway",
    "connection refused", "connection closed", "remote disconnected",
)


def _is_transient(exc: Exception) -> bool:
    """Check if an exception looks like a transient failure."""
    msg = str(exc).lower()
    return any(hint in msg for hint in TRANSIENT_HINTS)


def retry_transient(
    func: Callable,
    max_attempts: int = 3,
    backoff_base: float = 1.0,
    backoff_max: float = 8.0,
    logger_name: str = "nally.tools.retry",
) -> Tuple[Any, Optional[Exception]]:
    """Call *func* with retry on transient errors.

    Args:
        func: Zero-arg callable to execute.
        max_attempts: Total attempts (1 = no retry).
        backoff_base: Initial backoff in seconds.
        backoff_max: Maximum backoff cap.
        logger_name: Logger name for retry messages.

    Returns:
        (result, None) on success, (None, last_exception) on failure.
    """
    log = logging.getLogger(logger_name)
    last_exc: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        try:
            return func(), None
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts or not _is_transient(exc):
                return None, exc

            delay = min(backoff_base * (2 ** (attempt - 1)), backoff_max)
            log.warning(
                "Transient failure (attempt %d/%d), retrying in %.1fs: %s",
                attempt, max_attempts, delay, str(exc)[:120],
            )
            time.sleep(delay)

    return None, last_exc


def retry_transient_async(
    func: Callable,
    max_attempts: int = 3,
    backoff_base: float = 1.0,
    backoff_max: float = 8.0,
    logger_name: str = "nally.tools.retry",
) -> Tuple[Any, Optional[Exception]]:
    """Async version of retry_transient for use with async httpx clients.

    Args:
        func: Async zero-arg callable to execute.
        max_attempts: Total attempts (1 = no retry).
        backoff_base: Initial backoff in seconds.
        backoff_max: Maximum backoff cap.
        logger_name: Logger name for retry messages.

    Returns:
        (result, None) on success, (None, last_exception) on failure.
    """
    import asyncio
    log = logging.getLogger(logger_name)
    last_exc: Optional[Exception] = None

    for attempt in range(1, max_attempts + 1):
        try:
            result = func()
            # Support both sync and async callables
            if hasattr(result, "__await__"):
                import asyncio
                result = asyncio.get_event_loop().run_until_complete(result)
            return result, None
        except Exception as exc:
            last_exc = exc
            if attempt >= max_attempts or not _is_transient(exc):
                return None, exc

            delay = min(backoff_base * (2 ** (attempt - 1)), backoff_max)
            log.warning(
                "Transient failure (attempt %d/%d), retrying in %.1fs: %s",
                attempt, max_attempts, delay, str(exc)[:120],
            )
            time.sleep(delay)

    return None, last_exc
