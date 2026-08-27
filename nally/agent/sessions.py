"""Session Manager — per-session NallyAgent instances with thread safety.

Each session gets its own agent with isolated conversation history and
LangGraph thread. Memory (facts/episodes) stays global across sessions.

Since cross-platform unification, DMs from bot/Telethon/web/voice/VoIP all
share the owner's single session (see agent/identity.py); groups keep their
own per-group session.
"""

import threading
import time
from typing import Callable, Dict, List, Optional

from ..utils.logger import logger
from .core import NallyAgent
from .identity import ensure_migrated

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

    def _effective_key(self, session_id: str, route_key: Optional[str] = None) -> str:
        """Effective pool key — route_key isolates chat history per channel, session_id is brain."""
        return route_key if route_key is not None else session_id

    def _get_lock(self, session_id: str, route_key: Optional[str] = None) -> threading.Lock:
        """Get or create a lock for a session (per-route for isolated history)."""
        key = self._effective_key(session_id, route_key)
        if key not in self._locks:
            with self._pool_lock:
                if key not in self._locks:
                    self._locks[key] = threading.Lock()
        return self._locks[key]

    def get(self, session_id: str, channel: Optional[str] = None, route_key: Optional[str] = None) -> NallyAgent:
        """Get or create an agent for a session (per-route for history isolation)."""
        key = self._effective_key(session_id, route_key)
        if key not in self._sessions:
            with self._pool_lock:
                if key not in self._sessions:
                    ensure_migrated()
                    logger.info(f"Creating agent for session: {session_id} route: {key}")
                    self._sessions[key] = NallyAgent(
                        session_id=session_id, channel=channel, route_key=key
                    )
        return self._sessions[key]

    def commit_turn(self, session_id: str, user_text: str, reply: str, route_key: Optional[str] = None) -> None:
        """Commit an externally-generated turn into the shared session brain.

        Used by the voice-call fast path (and any other lightweight LLM path)
        so cross-platform history stays complete without paying full agent
        latency. Acquires the session lock so it can't interleave with a
        concurrent process() on the same brain.
        """
        lock = self._get_lock(session_id, route_key)
        with lock:
            try:
                agent = self.get(session_id, route_key=route_key)
                agent.messages.append({"role": "user", "content": user_text})
                if reply:
                    agent.messages.append({"role": "assistant", "content": reply})
                agent._save_history()
            except Exception as e:
                logger.error(f"commit_turn failed: {type(e).__name__}: {e}")

    def is_busy(self, session_id: str, route_key: Optional[str] = None) -> bool:
        """Check if session is currently processing a message (per-route)."""
        key = self._effective_key(session_id, route_key)
        with self._queue_lock:
            return self._busy.get(key, False)

    def queue_message(self, session_id: str, message: str, route_key: Optional[str] = None) -> int:
        """Queue a message for later processing. Returns queue position (1-based), or 0 if rejected."""
        key = self._effective_key(session_id, route_key)
        with self._queue_lock:
            q = self._queue.setdefault(key, [])
            if len(q) >= MAX_QUEUE_SIZE:
                return -1  # Queue full
            q.append(message)
            return len(q)

    def process(self, session_id: str, message: str, emit: Optional[Callable] = None, route_key: Optional[str] = None) -> str:
        """Process a message for a specific session (thread-safe, per-route).

        Sets busy flag while processing, then drains queued messages.
        """
        key = self._effective_key(session_id, route_key)
        lock = self._get_lock(session_id, route_key)
        with lock:
            with self._queue_lock:
                self._busy[key] = True
                self._last_activity[key] = time.time()
            try:
                agent = self.get(session_id, route_key=route_key)
                result = agent.process(message, emit=emit)
                return result
            finally:
                with self._queue_lock:
                    self._busy[key] = False
                    self._last_activity[key] = time.time()
                self._drain_queue(session_id, route_key)

    def _drain_queue(self, session_id: str, route_key: Optional[str] = None):
        """Process any queued messages after current op finishes."""
        key = self._effective_key(session_id, route_key)
        with self._queue_lock:
            q = self._queue.get(key, [])
            queued = list(q)
            q.clear()
        if not queued:
            return
        agent = self.get(session_id, route_key=route_key)
        for msg in queued:
            logger.info(f"Processing queued message for {session_id} route {key}")
            try:
                agent.process(msg)
            except Exception as e:
                logger.error(f"Queued message failed: {type(e).__name__}: {e}")
        with self._queue_lock:
            self._last_activity[key] = time.time()

    def get_history(self, session_id: str, route_key: Optional[str] = None) -> list:
        """Get conversation history for a session (per-route if route_key given)."""
        agent = self.get(session_id, route_key=route_key)
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
