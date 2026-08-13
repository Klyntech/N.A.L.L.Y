"""Shared abort flags — thread-safe session abort tracking.

Used by both agent (graph.py, planner.py) and web (app.py, ws_handler.py)
to avoid circular imports between agent and web layers.
"""

import threading

_flags: dict[str, bool] = {}
_lock = threading.Lock()
# Transient graph thread-ids -> stable session-id. The graph uses a fresh
# uuid-suffixed thread_id per invocation (see agent/graph.run_agent), so abort
# flags set under the session id would never match. Aliases bridge them so the
# flag set via set_abort(session_id) is visible to check_abort(fresh_thread).
_aliases: dict[str, str] = {}
_alias_lock = threading.Lock()


def register_alias(alias: str, canonical: str):
    """Map a transient thread_id alias to its stable session id."""
    with _alias_lock:
        _aliases[alias] = canonical


def clear_alias(alias: str):
    """Remove a thread_id alias (called when the graph invocation completes)."""
    with _alias_lock:
        _aliases.pop(alias, None)


def _resolve(key: str) -> str:
    """Resolve a thread_id through the alias map to the stable session id."""
    with _alias_lock:
        return _aliases.get(key, key)


def check_abort(session_id: str) -> bool:
    """Check if user requested abort for this session."""
    key = _resolve(session_id)
    with _lock:
        return _flags.get(key, False)


def set_abort(session_id: str):
    """Set abort flag for this session."""
    with _lock:
        _flags[session_id] = True


def clear_abort(session_id: str):
    """Clear abort flag for this session."""
    key = _resolve(session_id)
    with _lock:
        _flags.pop(key, None)
