"""Session Manager — per-session NallyAgent instances with thread safety.

Each session (web, Telegram DM, Telegram group) gets its own agent with
isolated conversation history and LangGraph thread. Memory (facts/episodes)
stays global across sessions.
"""

import threading
import time
from typing import Callable, Dict, List, Optional

from ..utils.logger import logger
from .core import NallyAgent

MAX_QUEUE_SIZE = 5


class AgentSessionManager:
    """Thread-safe pool of per-session NallyAgent instances."""

    def __init__(self):
        self._sessions: Dict[str, NallyAgent] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._busy: Dict[str, bool] = {}
        self._queue: Dict[str, List[str]] = {}
        self._last_activity: Dict[str, float] = {}
        self._pool_lock = threading.Lock()
        # Guards _busy/_queue across the process/queue_message/is_busy paths.
        self._queue_lock = threading.Lock()

    def _get_lock(self, session_id: str) -> threading.Lock:
        """Get or create a lock for a session."""
        if session_id not in self._locks:
            with self._pool_lock:
                if session_id not in self._locks:
                    self._locks[session_id] = threading.Lock()
        return self._locks[session_id]

    def get(self, session_id: str) -> NallyAgent:
        """Get or create an agent for a session."""
        if session_id not in self._sessions:
            with self._pool_lock:
                if session_id not in self._sessions:
                    logger.info(f"Creating agent for session: {session_id}")
                    self._sessions[session_id] = NallyAgent(session_id=session_id)
        return self._sessions[session_id]

    def is_busy(self, session_id: str) -> bool:
        """Check if session is currently processing a message."""
        with self._queue_lock:
            return self._busy.get(session_id, False)

    def queue_message(self, session_id: str, message: str) -> int:
        """Queue a message for later processing. Returns queue position (1-based), or 0 if rejected."""
        with self._queue_lock:
            q = self._queue.setdefault(session_id, [])
            if len(q) >= MAX_QUEUE_SIZE:
                return -1  # Queue full
            q.append(message)
            return len(q)

    def process(self, session_id: str, message: str, emit: Optional[Callable] = None) -> str:
        """Process a message for a specific session (thread-safe).

        Sets busy flag while processing, then drains queued messages.
        """
        lock = self._get_lock(session_id)
        with lock:
            with self._queue_lock:
                self._busy[session_id] = True
                self._last_activity[session_id] = time.time()
            try:
                agent = self.get(session_id)
                result = agent.process(message, emit=emit)
                return result
            finally:
                with self._queue_lock:
                    self._busy[session_id] = False
                    self._last_activity[session_id] = time.time()
                self._drain_queue(session_id)

    def _drain_queue(self, session_id: str):
        """Process any queued messages after current op finishes."""
        with self._queue_lock:
            q = self._queue.get(session_id, [])
            queued = list(q)
            q.clear()
        agent = self.get(session_id)
        for msg in queued:
            logger.info(f"Processing queued message for {session_id}")
            try:
                agent.process(msg)
            except Exception as e:
                logger.error(f"Queued message failed: {type(e).__name__}: {e}")
        if queued:
            with self._queue_lock:
                self._last_activity[session_id] = time.time()

    def get_history(self, session_id: str) -> list:
        """Get conversation history for a session."""
        agent = self.get(session_id)
        return agent.get_history()

    def all_idle(self, idle_threshold: float = 300.0) -> bool:
        """Return True if no session has been active for idle_threshold seconds."""
        now = time.time()
        with self._queue_lock:
            for sid in self._sessions:
                if self._busy.get(sid, False):
                    return False
                last = self._last_activity.get(sid, 0)
                if (now - last) < idle_threshold:
                    return False
        return True

    def seconds_since_last_activity(self) -> float:
        """Seconds since any session was last active. 0 if never active."""
        now = time.time()
        with self._queue_lock:
            if not self._last_activity:
                return 0
            return now - max(self._last_activity.values())

    def active_session_ids(self) -> List[str]:
        """Return session IDs that are currently busy."""
        with self._queue_lock:
            return [sid for sid, busy in self._busy.items() if busy]

    def list_sessions(self) -> list:
        """List all active session IDs."""
        with self._pool_lock:
            return list(self._sessions.keys())


# Module-level singleton
session_manager = AgentSessionManager()
