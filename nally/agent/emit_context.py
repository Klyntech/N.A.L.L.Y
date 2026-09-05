"""Thread-local stream emit callback for the active agent graph invocation.

Separated from graph.py so human-checkpoint (and tests) can reach the same
callback WS/SSE install via run_agent without importing the full graph stack.
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Optional

_tlocal = threading.local()

EmitFn = Callable[[str, dict], Any]


def get_emit() -> Optional[EmitFn]:
    return getattr(_tlocal, "emit", None)


def set_emit(emit: Optional[EmitFn]) -> None:
    _tlocal.emit = emit


# Back-compat aliases used by graph.py
_get_emit = get_emit
_set_emit = set_emit
