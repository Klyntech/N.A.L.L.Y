"""Session Manager — per-session NallyAgent instances with thread safety.

Each session (web, Telegram DM, Telegram group) gets its own agent with
isolated conversation history and LangGraph thread. Memory (facts/episodes)
stays global across sessions.
"""

import threading
from typing import Callable, Dict, Optional

from ..utils.logger import logger
from .core import NallyAgent


class AgentSessionManager:
    """Thread-safe pool of per-session NallyAgent instances."""

    def __init__(self):
        self._sessions: Dict[str, NallyAgent] = {}
        self._locks: Dict[str, threading.Lock] = {}
        self._pool_lock = threading.Lock()

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

    def process(self, session_id: str, message: str, emit: Optional[Callable] = None) -> str:
        """Process a message for a specific session (thread-safe)."""
        lock = self._get_lock(session_id)
        with lock:
            agent = self.get(session_id)
            return agent.process(message, emit=emit)

    def get_history(self, session_id: str) -> list:
        """Get conversation history for a session."""
        agent = self.get(session_id)
        return agent.get_history()

    def list_sessions(self) -> list:
        """List all active session IDs."""
        with self._pool_lock:
            return list(self._sessions.keys())


# Module-level singleton
session_manager = AgentSessionManager()
