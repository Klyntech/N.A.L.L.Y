"""Actor Model Sub-Agents — isolated agents with async message passing.

Pattern from AutoGen v0.4: each agent is an isolated actor with its own
state, message inbox, and processing loop. Agents communicate via async
messages. One agent crashing doesn't crash others.

This wraps Nally's existing SubAgent with actor semantics.
"""

import asyncio
import logging
import threading
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("nally.actor")


@dataclass
class ActorMessage:
    """A message sent to an actor."""
    sender: str
    recipient: str
    content: Any
    topic: str = "default"
    timestamp: float = field(default_factory=lambda: __import__("time").time())
    message_id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:8]}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sender": self.sender,
            "recipient": self.recipient,
            "topic": self.topic,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
        }


class Actor:
    """An isolated agent with its own state and message inbox."""

    def __init__(self, actor_id: str, handler: Callable, state: Optional[Dict] = None):
        self.id = actor_id
        self._handler = handler
        self._inbox: deque = deque()
        self._state = state or {}
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._messages_sent = 0
        self._messages_received = 0

    def send(self, message: ActorMessage):
        """Send a message to this actor's inbox."""
        with self._lock:
            self._inbox.append(message)
            self._messages_received += 1

    def start(self):
        """Start the actor's processing loop."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._process_loop, daemon=True, name=f"Actor-{self.id}")
        self._thread.start()

    def stop(self):
        """Stop the actor."""
        self._running = False

    def _process_loop(self):
        """Process messages from the inbox."""
        while self._running:
            message = None
            with self._lock:
                if self._inbox:
                    message = self._inbox.popleft()

            if message:
                try:
                    self._handler(self, message, self._state)
                except Exception as e:
                    logger.warning(f"Actor {self.id} handler failed: {e}")
            else:
                # No messages — sleep briefly
                threading.Event().wait(0.1)

    def get_state(self) -> Dict[str, Any]:
        """Get actor state (thread-safe)."""
        with self._lock:
            return dict(self._state)

    def get_stats(self) -> Dict[str, Any]:
        """Get actor statistics."""
        return {
            "id": self.id,
            "running": self._running,
            "inbox_size": len(self._inbox),
            "messages_sent": self._messages_sent,
            "messages_received": self._messages_received,
            "state_keys": list(self._state.keys()),
        }


class ActorSystem:
    """System for managing isolated actors with async message passing."""

    def __init__(self):
        self._actors: Dict[str, Actor] = {}
        self._lock = threading.Lock()
        self._message_bus: List[ActorMessage] = []

    def create_actor(self, actor_id: str, handler: Callable, state: Optional[Dict] = None) -> Actor:
        """Create and register a new actor."""
        actor = Actor(actor_id, handler, state)
        with self._lock:
            self._actors[actor_id] = actor
        actor.start()
        logger.info(f"Actor created: {actor_id}")
        return actor

    def get_actor(self, actor_id: str) -> Optional[Actor]:
        """Get an actor by ID."""
        with self._lock:
            return self._actors.get(actor_id)

    def send(self, sender: str, recipient: str, content: Any, topic: str = "default"):
        """Send a message between actors."""
        msg = ActorMessage(sender=sender, recipient=recipient, content=content, topic=topic)
        self._message_bus.append(msg)

        actor = self.get_actor(recipient)
        if actor:
            actor.send(msg)
        else:
            logger.warning(f"Actor {recipient} not found")

    def broadcast(self, sender: str, content: Any, topic: str = "default"):
        """Broadcast a message to all actors."""
        with self._lock:
            recipients = list(self._actors.keys())

        for recipient in recipients:
            if recipient != sender:
                self.send(sender, recipient, content, topic)

    def remove_actor(self, actor_id: str):
        """Stop and remove an actor."""
        actor = self.get_actor(actor_id)
        if actor:
            actor.stop()
            with self._lock:
                del self._actors[actor_id]
            logger.info(f"Actor removed: {actor_id}")

    def get_all_stats(self) -> List[Dict]:
        """Get stats for all actors."""
        with self._lock:
            return [a.get_stats() for a in self._actors.values()]

    def stop_all(self):
        """Stop all actors."""
        with self._lock:
            for actor in self._actors.values():
                actor.stop()


# Singleton
actor_system = ActorSystem()
