"""OpenTelemetry tracing, optional. If opentelemetry is not installed the
helpers become no-ops, so the gateway runs with zero tracing deps. When it is
installed and GW_OTEL_ENABLED=1, spans export via OTLP (to Tempo / Jaeger /
Cloud Trace). Span attributes follow the GenAI semantic-convention style
(gen_ai.*), so a request can be followed edge -> gateway -> provider.
"""

from __future__ import annotations

import os
from contextlib import contextmanager

try:
    from opentelemetry import trace
    _HAS_OTEL = True
except ImportError:
    _HAS_OTEL = False


class _NoopSpan:
    def set_attribute(self, *_args, **_kwargs) -> None:
        pass


def setup_tracing() -> None:
    """Configure an OTLP exporter. Only touches the global provider when
    explicitly enabled, so tests can install their own in-memory provider."""
    if not _HAS_OTEL or os.environ.get("GW_OTEL_ENABLED", "0") != "1":
        return
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

    provider = TracerProvider(resource=Resource.create({"service.name": "llm-gateway"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)


@contextmanager
def start_span(name: str):
    """Start a span under whatever global provider is active. Yields a span
    with .set_attribute; a no-op object when otel is absent."""
    if _HAS_OTEL:
        tracer = trace.get_tracer("llm-gateway")
        with tracer.start_as_current_span(name) as span:
            yield span
    else:
        yield _NoopSpan()
