# tests/test_intent_adaptive_models.py
"""Smoke tests for intent_adaptive domain models (Step 1)."""

import pytest
from pydantic import ValidationError

from adami_kernel.cortex.intent_adaptive import (
    IntentClassificationResult,
    IntentFamily,
    IntentType,
    default_unknown_result,
)


def test_import_package_exports() -> None:
    from adami_kernel.cortex import intent_adaptive as ia

    assert ia.IntentFamily.UNKNOWN.value == "unknown"
    assert ia.default_unknown_result().route == "dynamic"


def test_intent_classification_result_valid() -> None:
    r = IntentClassificationResult(
        primary_family=IntentFamily.RETRIEVAL,
        primary_type="retrieval.weather",
        confidence=0.85,
        slots={"city": "Tokyo", "units": "metric"},
        route="template",
        reason_codes=["rule_hit"],
    )
    assert r.primary_family == IntentFamily.RETRIEVAL
    assert r.slots["city"] == "Tokyo"


def test_intent_classification_slots_key_validation() -> None:
    with pytest.raises(ValidationError):
        IntentClassificationResult(
            primary_family=IntentFamily.UNKNOWN,
            primary_type=IntentType.UNKNOWN,
            confidence=0.1,
            slots={"BadKey": "x"},
            route="dynamic",
        )


def test_default_unknown_result() -> None:
    u = default_unknown_result(reason_codes=["smoke"])
    assert u.primary_type == IntentType.UNKNOWN
    assert u.confidence == 0.0
    assert u.reason_codes == ["smoke"]
