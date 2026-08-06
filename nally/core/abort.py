"""Shared abort flags — thread-safe session abort tracking.

Used by both agent (graph.py, planner.py) and web (app.py, ws_handler.py)
to avoid circular imports between agent and web layers.
"""

import threading

_flags: dict[str, bool] = {}
_lock = threading.Lock()


def check_abort(session_id: str) -> bool:
    """Check if user requested abort for this session."""
    with _lock:
        return _flags.get(session_id, False)


def set_abort(session_id: str):
    """Set abort flag for this session."""
    with _lock:
        _flags[session_id] = True


def clear_abort(session_id: str):
    """Clear abort flag for this session."""
    with _lock:
        _flags.pop(session_id, None)
