"""Typed Event Streaming — structured event projections for FastAPI SSE.

Provides typed event categories so the frontend can cleanly separate:
    - LLM tokens (real-time text streaming)
    - Tool events (call status, results, diffs)
    - System events (notices, warnings, budget alerts)
    - Checkpoint events (human review required)
    - Custom events (arbitrary data from nodes)

Each event carries a type, namespace, and typed payload.
Frontend subscribes to specific projections, not raw event soup.
"""

import json
import time
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Callable, Dict, List, Optional


class EventType(StrEnum):
    # LLM streaming
    STREAM_CHUNK = "stream_chunk"
    STREAM_DONE = "stream_done"

    # Tool lifecycle
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    TOOL_VERIFICATION = "tool_verification"
    CONFIRMATION_REQUIRED = "confirmation_required"

    # System
    SYSTEM_NOTICE = "system_notice"
    THOUGHT = "thought"
    RUN_ID = "run_id"

    # Human checkpoint
    HUMAN_CHECKPOINT = "human_checkpoint_required"
    CHECKPOINT_RESOLVED = "checkpoint_resolved"

    # Verification
    VERIFICATION = "verification"
    CRITIQUE = "critique"

    # Errors
    ERROR = "error"


@dataclass
class StreamEvent:
    """A single typed event in the stream."""
    type: EventType
    data: Dict[str, Any]
    namespace: str = "agent"  # agent, tool, system, checkpoint
    timestamp: float = field(default_factory=time.time)
    run_id: Optional[str] = None

    def to_sse(self) -> str:
        """Format as SSE string."""
        payload = {
            "type": self.type.value,
            "namespace": self.namespace,
            "data": self.data,
            "timestamp": self.timestamp,
        }
        if self.run_id:
            payload["run_id"] = self.run_id
        return f"event: {self.type.value}\ndata: {json.dumps(payload)}\n\n"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type.value,
            "namespace": self.namespace,
            "data": self.data,
            "timestamp": self.timestamp,
            "run_id": self.run_id,
        }


class EventEmitter:
    """Typed event emitter with projection support.

    Usage:
        emitter = EventEmitter(emit_fn)

        # Emit typed events
        emitter.stream_chunk("Hello world")
        emitter.tool_call("web_search", {"query": "news"})
        emitter.system_notice("Token budget warning")

        # Or emit raw
        emitter.emit(EventType.TOOL_RESULT, {"name": "web_search", "result": "..."})
    """

    def __init__(self, emit_fn: Optional[Callable] = None, run_id: Optional[str] = None):
        self._emit_fn = emit_fn
        self._run_id = run_id
        self._events: List[StreamEvent] = []

    def set_run_id(self, run_id: str):
        self._run_id = run_id

    def emit(self, event_type: EventType, data: Dict[str, Any], namespace: str = "agent"):
        """Emit a typed event."""
        event = StreamEvent(
            type=event_type,
            data=data,
            namespace=namespace,
            run_id=self._run_id,
        )
        self._events.append(event)

        if self._emit_fn:
            try:
                self._emit_fn(event_type.value, data)
            except Exception:
                pass

    # ── LLM Streaming ──────────────────────────────────

    def stream_chunk(self, text: str):
        """Emit an LLM text chunk for real-time streaming."""
        self.emit(EventType.STREAM_CHUNK, {"text": text}, namespace="llm")

    def stream_done(self):
        """Signal end of LLM stream."""
        self.emit(EventType.STREAM_DONE, {}, namespace="llm")

    # ── Tool Events ────────────────────────────────────

    def tool_call(self, name: str, args: dict, iteration: int = 0, tool_call_id: str = ""):
        """Emit tool call started."""
        self.emit(EventType.TOOL_CALL, {
            "name": name,
            "args": args,
            "iteration": iteration,
            "id": tool_call_id,
        }, namespace="tool")

    def tool_result(self, name: str, result: str, duration_ms: int = 0, success: bool = True,
                    diff: str = None, file_path: str = None, tool_call_id: str = ""):
        """Emit tool call result."""
        data = {
            "name": name,
            "result": result[:500] if result else "",
            "duration_ms": duration_ms,
            "success": success,
            "id": tool_call_id,
        }
        if diff:
            data["diff"] = diff
            data["file_path"] = file_path
        self.emit(EventType.TOOL_RESULT, data, namespace="tool")

    def confirmation_required(self, tool_call_id: str, name: str, args: dict,
                              diff: str = None, file_path: str = None):
        """Emit tool approval request."""
        data = {
            "tool_call_id": tool_call_id,
            "name": name,
            "args": args,
            "permission": "ask",
        }
        if diff:
            data["diff"] = diff
            data["file_path"] = file_path
        self.emit(EventType.CONFIRMATION_REQUIRED, data, namespace="checkpoint")

    # ── System Events ──────────────────────────────────

    def system_notice(self, text: str):
        """Emit a system notice (budget warning, abort, etc.)."""
        self.emit(EventType.SYSTEM_NOTICE, {"text": text}, namespace="system")

    def thought(self, text: str):
        """Emit agent thought/reasoning."""
        self.emit(EventType.THOUGHT, {"text": text[:500]}, namespace="system")

    def run_id(self, run_id: str):
        """Emit run ID for trace linking."""
        self.emit(EventType.RUN_ID, {"run_id": run_id}, namespace="system")

    # ── Checkpoint Events ──────────────────────────────

    def human_checkpoint(self, plan_summary: str, steps: list, task_class: str):
        """Emit human checkpoint required."""
        self.emit(EventType.HUMAN_CHECKPOINT, {
            "plan_summary": plan_summary,
            "steps": steps,
            "task_class": task_class,
        }, namespace="checkpoint")

    def checkpoint_resolved(self, thread_id: str, action: str):
        """Emit checkpoint resolution."""
        self.emit(EventType.CHECKPOINT_RESOLVED, {
            "thread_id": thread_id,
            "action": action,
        }, namespace="checkpoint")

    # ── Verification Events ────────────────────────────

    def verification(self, findings: dict):
        """Emit claim verification results."""
        self.emit(EventType.VERIFICATION, findings, namespace="system")

    def critique(self, critique_data: dict):
        """Emit critique pipeline results."""
        self.emit(EventType.CRITIQUE, critique_data, namespace="system")

    # ── Error Events ───────────────────────────────────

    def error(self, message: str, code: str = ""):
        """Emit an error event."""
        self.emit(EventType.ERROR, {"message": message, "code": code}, namespace="system")

    # ── History ────────────────────────────────────────

    def get_events(self, namespace: Optional[str] = None) -> List[StreamEvent]:
        """Get emitted events, optionally filtered by namespace."""
        if namespace:
            return [e for e in self._events if e.namespace == namespace]
        return list(self._events)

    def get_event_count(self) -> Dict[str, int]:
        """Get count of events by type."""
        counts = {}
        for e in self._events:
            counts[e.type.value] = counts.get(e.type.value, 0) + 1
        return counts

    def clear_history(self):
        """Clear event history."""
        self._events.clear()


class ProjectionFilter:
    """Filter events by namespace for frontend projections."""

    @staticmethod
    def llm_tokens(events: List[StreamEvent]) -> List[Dict]:
        """Extract only LLM streaming tokens."""
        return [e.to_dict() for e in events if e.namespace == "llm"]

    @staticmethod
    def tool_events(events: List[StreamEvent]) -> List[Dict]:
        """Extract only tool lifecycle events."""
        return [e.to_dict() for e in events if e.namespace == "tool"]

    @staticmethod
    def system_events(events: List[StreamEvent]) -> List[Dict]:
        """Extract only system events."""
        return [e.to_dict() for e in events if e.namespace == "system"]

    @staticmethod
    def checkpoint_events(events: List[StreamEvent]) -> List[Dict]:
        """Extract only checkpoint/human-review events."""
        return [e.to_dict() for e in events if e.namespace == "checkpoint"]

    @staticmethod
    def all_projections(events: List[StreamEvent]) -> Dict[str, List[Dict]]:
        """Get all projections at once."""
        return {
            "llm": ProjectionFilter.llm_tokens(events),
            "tools": ProjectionFilter.tool_events(events),
            "system": ProjectionFilter.system_events(events),
            "checkpoints": ProjectionFilter.checkpoint_events(events),
        }
