"""OpenTelemetry tracing emits the expected spans. Skips when otel is not
installed (local dev), runs in CI where the lock installs it."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

pytest.importorskip("opentelemetry.sdk.trace")


def test_route_emits_spans_with_genai_attributes():
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    exporter = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    from gateway.router import AsyncRouter
    from gateway.store import MemoryStore
    from router.types import CompletionRequest

    router = AsyncRouter(MemoryStore())
    asyncio.run(router.route(CompletionRequest(prompt="What is the capital of France?")))

    spans = exporter.get_finished_spans()
    names = [s.name for s in spans]
    assert "gateway.route" in names
    assert any(n.startswith("gateway.attempt.") for n in names)

    root = next(s for s in spans if s.name == "gateway.route")
    assert root.attributes.get("gen_ai.request.difficulty") == "easy"
    assert "gateway.escalated" in root.attributes
