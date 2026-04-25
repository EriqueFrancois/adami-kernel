# src/adami_kernel/cortex/intent_adaptive/telemetry.py
"""Intent-adaptive observability: stable span attribute keys + safe ``set_attribute``."""

from __future__ import annotations

from typing import Any

from adami_kernel.cortex.intent_adaptive.models import IntentClassificationResult

# OpenTelemetry-style dotted keys (DecisionProcessor / AGL train tracer).
ATTR_INTENT_FAMILY = "intent.family"
ATTR_INTENT_TYPE = "intent.type"
ATTR_INTENT_CONFIDENCE = "intent.confidence"
ATTR_INTENT_ROUTE = "intent.route"


def _family_wire(result: IntentClassificationResult) -> str:
    fam = result.primary_family
    return fam.value if hasattr(fam, "value") else str(fam)


def record_intent_classification_on_span(
    span: Any,
    classification: IntentClassificationResult,
) -> None:
    """
    Best-effort: copy the current tier classification onto the active trace span.
    No-ops when ``span`` is ``None`` or ``set_attribute`` is missing (noop tracers).
    """
    if span is None or classification is None:
        return
    setter = getattr(span, "set_attribute", None)
    if not callable(setter):
        return
    try:
        setter(ATTR_INTENT_FAMILY, _family_wire(classification))
        setter(ATTR_INTENT_TYPE, str(classification.primary_type))
        setter(ATTR_INTENT_CONFIDENCE, float(classification.confidence))
        setter(ATTR_INTENT_ROUTE, str(classification.route))
    except Exception:
        # Never break the decision path for telemetry backends.
        return


def intent_span_attributes_dict(
    classification: IntentClassificationResult,
) -> dict[str, Any]:
    """Flat dict for experience_sink metadata or tests (same keys as span attributes)."""
    return {
        ATTR_INTENT_FAMILY: _family_wire(classification),
        ATTR_INTENT_TYPE: str(classification.primary_type),
        ATTR_INTENT_CONFIDENCE: float(classification.confidence),
        ATTR_INTENT_ROUTE: str(classification.route),
    }
