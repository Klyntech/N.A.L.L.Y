"""OpenTelemetry Tracing Dashboard — span visualization and cost tracking.

Extends Nally's existing tracer with dashboard-ready data formats.
Provides structured trace data for visualization in web UI.
"""

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nally.tracing_dashboard")


@dataclass
class SpanSummary:
    """Summarized span for dashboard display."""
    span_id: str
    name: str
    start_time: float
    end_time: float
    duration_ms: int
    status: str  # ok, error, pending
    parent_id: Optional[str] = None
    run_id: Optional[str] = None
    input_summary: str = ""
    output_summary: str = ""
    error: Optional[str] = None
    token_count: int = 0
    cost_usd: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "span_id": self.span_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_ms": self.duration_ms,
            "status": self.status,
            "parent_id": self.parent_id,
            "run_id": self.run_id,
            "input_summary": self.input_summary[:200],
            "output_summary": self.output_summary[:200],
            "error": self.error,
            "token_count": self.token_count,
            "cost_usd": self.cost_usd,
        }


@dataclass
class TraceSummary:
    """Summarized trace for dashboard display."""
    run_id: str
    start_time: float
    end_time: float
    total_duration_ms: int
    spans: List[SpanSummary]
    total_tokens: int = 0
    total_cost_usd: float = 0.0
    status: str = "ok"
    error_count: int = 0
    tool_count: int = 0
    llm_call_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_duration_ms": self.total_duration_ms,
            "span_count": len(self.spans),
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "status": self.status,
            "error_count": self.error_count,
            "tool_count": self.tool_count,
            "llm_call_count": self.llm_call_count,
            "spans": [s.to_dict() for s in self.spans],
        }


class TracingDashboard:
    """Dashboard data provider for execution traces."""

    def __init__(self):
        self._traces: List[TraceSummary] = []
        self._max_traces = 100

    def record_trace(self, trace: TraceSummary):
        """Record a completed trace."""
        self._traces.append(trace)
        if len(self._traces) > self._max_traces:
            self._traces = self._traces[-self._max_traces:]

    def get_recent_traces(self, limit: int = 20) -> List[Dict]:
        """Get recent traces for dashboard."""
        return [t.to_dict() for t in self._traces[-limit:]]

    def get_trace(self, run_id: str) -> Optional[Dict]:
        """Get a specific trace by run_id."""
        for t in self._traces:
            if t.run_id == run_id:
                return t.to_dict()
        return None

    def get_stats(self) -> Dict[str, Any]:
        """Get aggregate statistics for dashboard."""
        if not self._traces:
            return {"traces": 0}

        total_tokens = sum(t.total_tokens for t in self._traces)
        total_cost = sum(t.total_cost_usd for t in self._traces)
        avg_duration = sum(t.total_duration_ms for t in self._traces) / len(self._traces)
        error_traces = sum(1 for t in self._traces if t.error_count > 0)

        return {
            "traces": len(self._traces),
            "total_tokens": total_tokens,
            "total_cost_usd": total_cost,
            "avg_duration_ms": avg_duration,
            "error_rate": error_traces / len(self._traces) if self._traces else 0,
            "avg_spans_per_trace": sum(len(t.spans) for t in self._traces) / len(self._traces),
        }

    def build_trace_from_spans(self, spans: List[Dict], run_id: str) -> TraceSummary:
        """Build a TraceSummary from raw span data."""
        if not spans:
            return TraceSummary(
                run_id=run_id,
                start_time=0, end_time=0,
                total_duration_ms=0, spans=[],
            )

        start_time = min(s.get("start_time", 0) for s in spans)
        end_time = max(s.get("end_time", 0) for s in spans)

        span_summaries = []
        total_tokens = 0
        total_cost = 0.0
        error_count = 0
        tool_count = 0
        llm_count = 0

        for s in spans:
            name = s.get("name", "")
            if name.startswith("tool:"):
                tool_count += 1
            elif name in ("llm_call", "plan_generate"):
                llm_count += 1

            tokens = s.get("token_count", 0)
            total_tokens += tokens
            total_cost += s.get("cost_usd", 0)

            if s.get("error"):
                error_count += 1

            span_summaries.append(SpanSummary(
                span_id=s.get("span_id", ""),
                name=name,
                start_time=s.get("start_time", 0),
                end_time=s.get("end_time", 0),
                duration_ms=int((s.get("end_time", 0) - s.get("start_time", 0)) * 1000),
                status="error" if s.get("error") else "ok",
                parent_id=s.get("parent_id"),
                run_id=s.get("run_id"),
                input_summary=str(s.get("input", ""))[:200],
                output_summary=str(s.get("output", ""))[:200],
                error=s.get("error"),
                token_count=tokens,
                cost_usd=s.get("cost_usd", 0),
            ))

        return TraceSummary(
            run_id=run_id,
            start_time=start_time,
            end_time=end_time,
            total_duration_ms=int((end_time - start_time) * 1000),
            spans=span_summaries,
            total_tokens=total_tokens,
            total_cost_usd=total_cost,
            status="error" if error_count > 0 else "ok",
            error_count=error_count,
            tool_count=tool_count,
            llm_call_count=llm_count,
        )


# Singleton
tracing_dashboard = TracingDashboard()
