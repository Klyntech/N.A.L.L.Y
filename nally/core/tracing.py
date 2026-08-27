"""Execution Tracer — nested span recording for every agent turn.

Self-hosted in the SQLite memory store. No external services, no data leaving
the machine. Thread-safe via a thread-local current-span stack (mirrors the
_get_emit()/_set_emit() pattern in graph.py).

If tracing records a failure, it logs and moves on — it must never affect the
underlying operation being traced.
"""

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Span:
    span_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    parent_span_id: Optional[str] = None
    run_id: str = ""
    name: str = ""
    status: str = "running"  # "running" | "ok" | "error"
    input: Dict[str, Any] = field(default_factory=dict)
    output: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    ended_at: Optional[float] = None

    @property
    def duration_ms(self) -> Optional[float]:
        if self.ended_at:
            return round((self.ended_at - self.started_at) * 1000, 1)
        return None

    def to_dict(self) -> dict:
        return {
            "span_id": self.span_id,
            "parent_span_id": self.parent_span_id,
            "run_id": self.run_id,
            "name": self.name,
            "status": self.status,
            "input": self.input,
            "output": self.output,
            "error": self.error,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
        }


class _SpanStack(threading.local):
    """Thread-local active span stack."""

    def __init__(self):
        super().__init__()
        self.spans: List[Span] = []


_tlocal = _SpanStack()


def _get_stack() -> List[Span]:
    if not hasattr(_tlocal, "spans") or _tlocal.spans is None:
        _tlocal.spans = []
    return _tlocal.spans


class Tracer:
    """Records nested spans. Parent spans are auto-detected via thread-local stack."""

    def __init__(self, store=None):
        self._store = store  # optional MemoryRepository

    def set_store(self, store):
        """Set the storage backend (injected once at startup)."""
        self._store = store

    def start_span(
        self,
        name: str,
        input: dict,
        parent_span_id: Optional[str] = None,
        run_id: Optional[str] = None,
    ) -> Span:
        """Start a new span. Auto-detects parent + run_id from thread-local stack."""
        stack = _get_stack()

        if parent_span_id is None and stack:
            parent_span_id = stack[-1].span_id

        if run_id is None and stack:
            run_id = stack[0].run_id

        span = Span(
            parent_span_id=parent_span_id,
            run_id=run_id or uuid.uuid4().hex[:16],
            name=name,
            input=input or {},
        )

        stack.append(span)
        return span

    def end_span(
        self,
        span_id: str,
        output: Optional[dict] = None,
        error: Optional[str] = None,
    ) -> Optional[Span]:
        """End a span, pop it from the stack, and persist best-effort."""
        stack = _get_stack()

        target = None
        removed_idx = None
        for i, s in enumerate(stack):
            if s.span_id == span_id:
                target = s
                removed_idx = i
                break

        if target is None:
            return None

        # Pop the found span from the stack (handles out-of-order close)
        stack.pop(removed_idx)

        target.ended_at = time.time()
        target.output = output
        target.error = error
        target.status = "error" if error else "ok"

        self._persist(target)
        return target

    def end_span_exc(self, span_id: str, exc: BaseException) -> Optional[Span]:
        """End a span with an exception (records error message)."""
        return self.end_span(span_id, error=str(exc))

    def get_current_span(self) -> Optional[Span]:
        stack = _get_stack()
        return stack[-1] if stack else None

    def stack_depth(self) -> int:
        """Current thread-local span stack depth."""
        return len(_get_stack())

    def truncate_to(self, depth: int):
        """Pop spans until the stack is at `depth`. Used on run boundaries so a
        leaked span never bleeds into the next user turn."""
        stack = _get_stack()
        while len(stack) > depth:
            stack.pop()

    def get_run_tree(self, run_id: str) -> Optional[dict]:
        if not self._store:
            return None
        spans = self._store.get_spans_by_run(run_id)
        if not spans:
            return None
        return self._build_tree(spans)

    def list_runs(self, limit: int = 50) -> List[dict]:
        if not self._store:
            return []
        try:
            return self._store.list_recent_runs(limit)
        except Exception:
            return []

    def _build_tree(self, spans: List[dict]) -> dict:
        by_id = {}
        for s in spans:
            node = dict(s)
            node["children"] = []
            by_id[node["span_id"]] = node

        roots = []
        for s in spans:
            node = by_id[s["span_id"]]
            parent_id = s.get("parent_span_id")
            if parent_id and parent_id in by_id:
                by_id[parent_id]["children"].append(node)
            else:
                roots.append(node)

        def sort_children(node):
            node["children"].sort(key=lambda c: c["started_at"])
            for child in node["children"]:
                sort_children(child)

        for root in roots:
            sort_children(root)

        if len(roots) == 1:
            return roots[0]
        # Multiple roots (unlikely) — wrap in a synthetic root
        return {
            "span_id": "root",
            "parent_span_id": None,
            "run_id": roots[0]["run_id"] if roots else "",
            "name": "run",
            "status": "ok",
            "input": {},
            "output": None,
            "error": None,
            "started_at": min(r["started_at"] for r in roots) if roots else 0,
            "ended_at": max(r.get("ended_at") or r["started_at"] for r in roots) if roots else None,
            "duration_ms": None,
            "children": roots,
        }

    def _persist(self, span: Span):
        if not self._store:
            return
        # Retry once on transient SQLITE_BUSY; never silently drop spans
        for _attempt in range(2):
            try:
                self._store.save_span(span.to_dict())
                return
            except Exception as e:
                if "busy" in str(e).lower() and _attempt == 0:
                    try:
                        import time as _t
                        _t.sleep(0.05)
                        continue
                    except Exception:
                        pass
                try:
                    from ..utils.logger import logger

                    logger.warning(f"Tracer persist failed for {span.name} (attempt {_attempt + 1}): {e}")
                except Exception:
                    pass
                return


# Module-level singleton. Storage injected later via set_store().
tracer = Tracer()