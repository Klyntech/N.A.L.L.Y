"""Execution Tracer — nested span recording for every agent turn.

Dual-write: SQLite (always, free-tier local) + optional OTel OTLP (when
OTEL_EXPORTER_OTLP_ENDPOINT is set and opentelemetry is installed).
Thread-safe via thread-local stack. No failure in tracing ever affects the
operation being traced.
"""

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nally.tracing")

# Optional OTel — gracefully disabled when not installed or endpoint empty (Free tier)
_otel_tracer = None
_otel_initialized = False


def _init_otel():
    global _otel_tracer, _otel_initialized
    if _otel_initialized:
        return _otel_tracer
    _otel_initialized = True
    try:
        import os

        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
        if not endpoint:
            return None
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {
                "service.name": os.getenv("OTEL_SERVICE_NAME", "nally"),
                "service.version": os.getenv("NALLY_VERSION", "1.0.0"),
                "deployment.environment": os.getenv("NALLY_ENV", "production"),
            }
        )
        provider = TracerProvider(resource=resource)
        exporter = OTLPSpanExporter(endpoint=endpoint)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        trace.set_tracer_provider(provider)
        _otel_tracer = trace.get_tracer("nally.tracer")
        logger.info(f"OTel tracing enabled → {endpoint}")
        return _otel_tracer
    except Exception as e:
        logger.debug(f"OTel not enabled: {e}")
        return None


# Try init at import (no-op on Free when endpoint empty)
try:
    _init_otel()
except Exception:
    pass


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
    """Records nested spans. Dual-write: SQLite (always) + OTel OTLP when configured."""

    def __init__(self, store=None):
        self._store = store  # optional MemoryRepository
        self._otel_spans: Dict[str, Any] = {}  # span_id -> OTel span

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

        # Optional OTel span (no-op on Free when endpoint empty)
        try:
            otel = _otel_tracer or _init_otel()
            if otel:
                # Use OTel context propagation for parent — simplified: new span
                ospan = otel.start_span(name)
                # Add resource-like attributes
                try:
                    ospan.set_attribute("nally.span_id", span.span_id)
                    ospan.set_attribute("nally.run_id", span.run_id)
                    if parent_span_id:
                        ospan.set_attribute("nally.parent_span_id", parent_span_id)
                    # Truncate input to keep OTel payload small
                    for k, v in (input or {}).items():
                        try:
                            ospan.set_attribute(f"nally.input.{k}", str(v)[:256])
                        except Exception:
                            pass
                except Exception:
                    pass
                self._otel_spans[span.span_id] = ospan
        except Exception:
            pass

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

        # End OTel span if present
        try:
            ospan = self._otel_spans.pop(span_id, None)
            if ospan:
                try:
                    if output:
                        for k, v in output.items():
                            try:
                                ospan.set_attribute(f"nally.output.{k}", str(v)[:256])
                            except Exception:
                                pass
                    if error:
                        ospan.set_attribute("nally.error", str(error)[:512])
                        try:
                            from opentelemetry.trace import Status, StatusCode

                            ospan.set_status(Status(StatusCode.ERROR, str(error)[:256]))
                        except Exception:
                            pass
                    else:
                        try:
                            from opentelemetry.trace import Status, StatusCode

                            ospan.set_status(Status(StatusCode.OK))
                        except Exception:
                            pass
                    ospan.end()
                except Exception:
                    pass
        except Exception:
            pass

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
