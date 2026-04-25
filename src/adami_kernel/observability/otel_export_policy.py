"""
OTLP export policy: trace sampling resolution and span export redaction.

Sampling precedence:
1. ``Settings.ADAMI_OTEL_TRACES_SAMPLER`` when set (non-empty) uses ``ADAMI_OTEL_TRACES_SAMPLER_RATIO``
   for ``traceidratio`` / ``parentbased_traceidratio``.
2. Otherwise standard ``OTEL_TRACES_SAMPLER`` and ``OTEL_TRACES_SAMPLER_ARG`` (OpenTelemetry spec).

Redaction (export-time, before OTLP / console batch):
- Attribute keys matching token/secret/credential patterns → value ``[REDACTED]``.
- OpenAI-style ``sk-…`` substrings in string values → ``[REDACTED_KEY]``.
- Scalar string truncation to ``ADAMI_OTEL_EXPORT_ATTR_VALUE_MAX_LEN`` (grapheme-safe by rune count).
"""

from __future__ import annotations

import os
import re
from typing import Any, Mapping, Optional, Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace import sampling as trace_sampling
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

_SENSITIVE_KEY_FRAGMENTS = frozenset(
    (
        "password",
        "passwd",
        "pwd",
        "secret",
        "token",
        "api_key",
        "apikey",
        "authorization",
        "auth",
        "cookie",
        "set-cookie",
        "credential",
        "bearer",
        "private_key",
        "access_key",
    )
)


def _clamp_unit_rate(x: float) -> float:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 1.0
    if v < 0.0:
        return 0.0
    if v > 1.0:
        return 1.0
    return v


def resolve_trace_sampler(
    *,
    adami_sampler: Optional[str],
    adami_ratio: float,
) -> trace_sampling.Sampler:
    """Build the SDK :class:`~opentelemetry.sdk.trace.sampling.Sampler` for ``TracerProvider``."""
    raw = (adami_sampler or "").strip()
    if raw:
        name = raw.lower()
        ratio = _clamp_unit_rate(adami_ratio)
    else:
        name = (
            os.getenv(trace_sampling.OTEL_TRACES_SAMPLER, "parentbased_always_on").strip().lower()
        )
        try:
            ratio = _clamp_unit_rate(
                float(os.getenv(trace_sampling.OTEL_TRACES_SAMPLER_ARG, "1.0"))
            )
        except (TypeError, ValueError):
            ratio = 1.0

    if name == "always_on":
        return trace_sampling.ALWAYS_ON
    if name == "always_off":
        return trace_sampling.ALWAYS_OFF
    if name == "parentbased_always_on":
        return trace_sampling.DEFAULT_ON
    if name == "parentbased_always_off":
        return trace_sampling.DEFAULT_OFF
    if name == "traceidratio":
        return trace_sampling.TraceIdRatioBased(ratio)
    if name == "parentbased_traceidratio":
        return trace_sampling.ParentBasedTraceIdRatio(ratio)

    # Unknown name: behave like OTEL SDK and fall back to parentbased_always_on.
    return trace_sampling.DEFAULT_ON


def _key_is_sensitive(key: str) -> bool:
    lk = str(key).lower().replace("-", "_")
    return any(frag in lk for frag in _SENSITIVE_KEY_FRAGMENTS)


def _redact_scalar(value: Any, max_len: int) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value
    s = str(value)
    s = re.sub(r"sk-[a-zA-Z0-9]{16,}", "[REDACTED_KEY]", s, flags=re.I)
    s = re.sub(
        r"(?:api[_-]?key|token|secret)\s*[:=]\s*[\"']?[\w\-]{8,}",
        "credential=[REDACTED]",
        s,
        flags=re.I,
    )
    s = re.sub(r"Bearer\s+[\w\-\._~\+/]+=*", "Bearer [REDACTED]", s, flags=re.I)
    if max_len > 0 and len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def redact_span_attributes(
    attributes: Optional[Mapping[str, Any]],
    *,
    max_value_len: int,
) -> dict[str, Any]:
    if not attributes:
        return {}
    out: dict[str, Any] = {}
    for k, v in attributes.items():
        key = str(k)
        if _key_is_sensitive(key):
            out[key] = "[REDACTED]"
        else:
            out[key] = _redact_scalar(v, max_value_len)
    return out


class RedactingSpanExporter(SpanExporter):
    """Wraps a :class:`SpanExporter` and emits spans with redacted attributes / event attrs."""

    def __init__(
        self,
        inner: SpanExporter,
        *,
        max_value_len: int,
        enabled: bool = True,
    ) -> None:
        self._inner = inner
        self._max_value_len = int(max_value_len)
        self._enabled = bool(enabled)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        if not self._enabled:
            return self._inner.export(spans)
        from opentelemetry.sdk.trace import Event

        out: list[ReadableSpan] = []
        for sp in spans:
            ra = redact_span_attributes(
                dict(sp.attributes) if sp.attributes else {},
                max_value_len=self._max_value_len,
            )
            events = []
            for ev in sp.events:
                ea = (
                    redact_span_attributes(
                        dict(ev.attributes) if ev.attributes else {},
                        max_value_len=self._max_value_len,
                    )
                    if ev.attributes
                    else None
                )
                events.append(Event(ev.name, ea, ev.timestamp))
            out.append(
                ReadableSpan(
                    name=sp.name,
                    context=sp.context,
                    parent=sp.parent,
                    resource=sp.resource,
                    attributes=ra,
                    events=tuple(events),
                    links=tuple(sp.links),
                    kind=sp.kind,
                    instrumentation_scope=sp.instrumentation_scope,
                    status=sp.status,
                    start_time=sp.start_time,
                    end_time=sp.end_time,
                )
            )
        return self._inner.export(out)

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)
