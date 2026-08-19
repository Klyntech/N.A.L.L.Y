"""OpenTelemetry observability for the streaming voice pipeline.

Centralizes metric + trace setup. Exposes a Prometheus /metrics HTTP endpoint
and an optional OTLP trace exporter.

Metrics:
  - stt_latency_seconds        (histogram) time from audio sent to transcript
  - tts_latency_seconds        (histogram) time-to-first-byte + total synthesis
  - pipeline_end_to_end_seconds (histogram) mic -> spoken response
  - bargein_events_total       (counter)  confirmed user interruptions
  - pipeline_errors_total      (counter)  pipeline-level errors
  - stream_frames_total        (counter)  inbound audio frames processed

Call init_telemetry() once at process startup (in run_tg_call.py / main.py).
All helper recorders are no-ops until init_telemetry() succeeds, so importing
this module never fails when OpenTelemetry isn't installed.
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger("nally.voice.metrics")

# Module-level singletons (set by init_telemetry)
_meter = None
_tracer = None
_hist_stt = None
_hist_tts = None
_hist_e2e = None
_counter_bargein = None
_counter_errors = None
_counter_frames = None
_prom_server_port: Optional[int] = None
_initialized = False
_lock = threading.Lock()


def init_telemetry(
    service_name: str = "nally-voice",
    metrics_port: int = 8000,
    otlp_endpoint: str = "",
    service_version: str = "1.2.0",
    metric_reader=None,
    force: bool = False,
) -> bool:
    """Initialize OpenTelemetry metrics + tracing.

    Idempotent unless *force* is True. Starts a Prometheus HTTP server on
    *metrics_port* (if > 0 and no custom *metric_reader* given) and wires an
    OTLP span exporter when *otlp_endpoint* is provided.

    *metric_reader* lets tests inject an InMemoryMetricReader instead of the
    Prometheus reader (no HTTP server is started in that case).

    Returns True on success, False if OpenTelemetry is unavailable.
    """
    global _meter, _tracer, _initialized, _prom_server_port
    global _hist_stt, _hist_tts, _hist_e2e, _counter_bargein, _counter_errors, _counter_frames

    with _lock:
        if _initialized and not force:
            return True

        try:
            from opentelemetry import metrics as otel_metrics, trace as otel_trace
            from opentelemetry.sdk.resources import Resource
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider
        except Exception as e:  # pragma: no cover - optional dep
            logger.warning(f"OpenTelemetry not installed — metrics disabled: {e}")
            return False

        if metric_reader is None:
            try:
                from opentelemetry.exporter.prometheus import PrometheusMetricReader
            except Exception as e:  # pragma: no cover
                logger.warning(f"Prometheus reader unavailable: {e}")
                return False

        resource = Resource.create(
            {
                "service.name": service_name,
                "service.version": service_version,
            }
        )

        # Prometheus reader feeds the default prometheus_client registry.
        readers = [metric_reader] if metric_reader is not None else [PrometheusMetricReader()]
        meter_provider = MeterProvider(resource=resource, metric_readers=readers)
        # Use the local provider directly (avoids global set-provider override
        # errors when init_telemetry is called more than once per process).
        _meter = meter_provider.get_meter(service_name)

        # Tracing (optional OTLP exporter)
        tracer_provider = SDKTracerProvider()
        try:
            tracer_provider.resource = resource
        except Exception:
            pass
        if otlp_endpoint:
            try:
                from opentelemetry.sdk.trace.export import BatchSpanProcessor
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )

                exporter = OTLPSpanExporter(endpoint=otlp_endpoint)
                tracer_provider.add_span_processor(BatchSpanProcessor(exporter))
                logger.info(f"OTLP trace exporter enabled: {otlp_endpoint}")
            except Exception as e:
                logger.warning(f"OTLP exporter setup failed: {e}")
        _tracer = tracer_provider.get_tracer(service_name)

        # Instruments
        _hist_stt = _meter.create_histogram(
            "stt_latency_seconds",
            unit="s",
            description="Latency from audio chunk sent to final transcript received",
        )
        _hist_tts = _meter.create_histogram(
            "tts_latency_seconds",
            unit="s",
            description="Text-to-speech synthesis latency (time-to-first-byte)",
        )
        _hist_e2e = _meter.create_histogram(
            "pipeline_end_to_end_seconds",
            unit="s",
            description="End-to-end pipeline latency: inbound audio to outbound audio",
        )
        _counter_bargein = _meter.create_counter(
            "bargein_events_total",
            unit="{event}",
            description="Number of confirmed user barge-in interruptions",
        )
        _counter_errors = _meter.create_counter(
            "pipeline_errors_total",
            unit="{error}",
            description="Pipeline-level errors by stage",
        )
        _counter_frames = _meter.create_counter(
            "stream_frames_total",
            unit="{frame}",
            description="Inbound audio frames processed by the pipeline",
        )

        # Prometheus HTTP server
        if metrics_port and metrics_port > 0:
            try:
                from prometheus_client import start_http_server

                start_http_server(metrics_port)
                _prom_server_port = metrics_port
                logger.info(f"Prometheus /metrics exposed on :{metrics_port}")
            except Exception as e:
                logger.warning(f"Failed to start Prometheus server: {e}")

        _initialized = True
        logger.info(f"Telemetry initialized for {service_name}")
        return True


# ── Recorders (no-op until initialized) ──


def record_stt_latency(seconds: float, attributes: Optional[dict] = None):
    if _hist_stt is not None:
        _hist_stt.record(max(0.0, seconds), attributes or {})


def record_tts_latency(seconds: float, attributes: Optional[dict] = None):
    if _hist_tts is not None:
        _hist_tts.record(max(0.0, seconds), attributes or {})


def record_pipeline_latency(seconds: float, attributes: Optional[dict] = None):
    if _hist_e2e is not None:
        _hist_e2e.record(max(0.0, seconds), attributes or {})


def inc_bargein(attributes: Optional[dict] = None):
    if _counter_bargein is not None:
        _counter_bargein.add(1, attributes or {})


def inc_error(stage: str, attributes: Optional[dict] = None):
    if _counter_errors is not None:
        attrs = {"stage": stage}
        if attributes:
            attrs.update(attributes)
        _counter_errors.add(1, attrs)


def inc_frames(count: int = 1, attributes: Optional[dict] = None):
    if _counter_frames is not None:
        _counter_frames.add(count, attributes or {})


def get_tracer():
    return _tracer


@contextmanager
def timed_span(name: str, attributes: Optional[dict] = None):
    """Context manager that opens a span (no-op if tracing disabled)."""
    tracer = _tracer
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(name, attributes=attributes or {}) as span:
        yield span


def now() -> float:
    return time.monotonic()


def reset_telemetry():
    """Reset all telemetry singletons. Intended for tests / re-init."""
    global _meter, _tracer, _initialized, _prom_server_port
    global _hist_stt, _hist_tts, _hist_e2e, _counter_bargein, _counter_errors, _counter_frames
    with _lock:
        _meter = None
        _tracer = None
        _initialized = False
        _prom_server_port = None
        _hist_stt = None
        _hist_tts = None
        _hist_e2e = None
        _counter_bargein = None
        _counter_errors = None
        _counter_frames = None
