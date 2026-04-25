"""Tests for OTLP export sampling + redaction policy (step 8)."""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from adami_kernel.observability.otel_export_policy import (
    RedactingSpanExporter,
    redact_span_attributes,
    resolve_trace_sampler,
)


def test_resolve_sampler_adami_ratio_overrides_env(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "parentbased_traceidratio")
    monkeypatch.setenv("OTEL_TRACES_SAMPLER_ARG", "0.99")
    s = resolve_trace_sampler(adami_sampler="parentbased_traceidratio", adami_ratio=0.1)
    assert "TraceIdRatioBased{0.1}" in s.get_description()


def test_resolve_sampler_falls_back_to_env(monkeypatch) -> None:
    monkeypatch.setenv("OTEL_TRACES_SAMPLER", "always_off")
    s = resolve_trace_sampler(adami_sampler=None, adami_ratio=1.0)
    assert s.get_description() == "AlwaysOffSampler"


def test_redact_span_attributes_sensitive_keys() -> None:
    out = redact_span_attributes(
        {"Authorization": "Bearer secret-token", "safe": "ok"},
        max_value_len=100,
    )
    assert out["Authorization"] == "[REDACTED]"
    assert out["safe"] == "ok"


def test_redact_span_attributes_sk_pattern() -> None:
    out = redact_span_attributes(
        {"prompt": "use sk-123456789012345678901234567890"},
        max_value_len=500,
    )
    assert "[REDACTED_KEY]" in str(out["prompt"])


def test_redacting_exporter_on_end_to_end() -> None:
    inner = InMemorySpanExporter()
    exporter = RedactingSpanExporter(inner, max_value_len=80, enabled=True)
    sampler = resolve_trace_sampler(adami_sampler="always_on", adami_ratio=1.0)
    provider = TracerProvider(sampler=sampler)
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer("test_otel_policy")
    with tracer.start_as_current_span(
        "op",
        attributes={"user_password": "x", "note": "hello"},
    ):
        pass
    provider.shutdown()
    spans = inner.get_finished_spans()
    assert len(spans) == 1
    attrs = dict(spans[0].attributes)
    assert attrs.get("user_password") == "[REDACTED]"
    assert attrs.get("note") == "hello"
