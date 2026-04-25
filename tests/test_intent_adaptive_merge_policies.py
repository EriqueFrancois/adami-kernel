# tests/test_intent_adaptive_merge_policies.py
"""Step 4.1: multi-label family merge conflict table."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from adami_kernel.cortex.intent_adaptive import (
    IntentClassificationResult,
    IntentFamily,
    apply_family_merge_policy,
    parse_llm_classification_json,
)


def test_merge_system_wins_over_synthesis() -> None:
    r = IntentClassificationResult(
        primary_family=IntentFamily.SYNTHESIS,
        primary_type="synthesis.summary",
        confidence=0.9,
        slots={},
        route="dynamic",
        reason_codes=["llm_based"],
        family_candidates=[IntentFamily.SYSTEM, IntentFamily.RETRIEVAL],
    )
    m = apply_family_merge_policy(r, action_permission_granted=False)
    assert m.primary_family == IntentFamily.SYSTEM
    assert m.family_candidates == []
    assert m.route == "dynamic"
    assert "merge_family_system_wins" in m.reason_codes


def test_merge_system_wins_when_system_primary_with_extras() -> None:
    r = IntentClassificationResult(
        primary_family=IntentFamily.SYSTEM,
        primary_type="unknown",
        confidence=1.0,
        slots={},
        route="template",
        reason_codes=[],
        family_candidates=[IntentFamily.CONVERSATION],
    )
    m = apply_family_merge_policy(r, action_permission_granted=False)
    assert m.primary_family == IntentFamily.SYSTEM
    assert m.family_candidates == []


@pytest.mark.parametrize(
    ("primary", "candidates", "expected_primary", "expected_route", "needle"),
    [
        (
            IntentFamily.ACTION,
            [],
            IntentFamily.UNKNOWN,
            "clarify",
            "merge_action_requires_permission",
        ),
        (
            IntentFamily.ACTION,
            [IntentFamily.RETRIEVAL],
            IntentFamily.RETRIEVAL,
            "clarify",
            "merge_action_requires_permission",
        ),
        (
            IntentFamily.RETRIEVAL,
            [IntentFamily.ACTION],
            IntentFamily.RETRIEVAL,
            "clarify",
            "merge_action_requires_permission",
        ),
    ],
)
def test_merge_action_without_permission(
    primary: IntentFamily,
    candidates: list,
    expected_primary: IntentFamily,
    expected_route: str,
    needle: str,
) -> None:
    r = IntentClassificationResult(
        primary_family=primary,
        primary_type="test.type",
        confidence=0.7,
        slots={},
        route="dynamic",
        reason_codes=[],
        family_candidates=candidates,
    )
    m = apply_family_merge_policy(r, action_permission_granted=False)
    assert m.primary_family == expected_primary
    assert m.route == expected_route
    assert needle in m.reason_codes
    if primary == IntentFamily.ACTION and not candidates:
        assert "merge_action_rejected" in m.reason_codes


def test_merge_action_with_permission_keeps_primary_and_strips_dupes() -> None:
    r = IntentClassificationResult(
        primary_family=IntentFamily.ACTION,
        primary_type="action.send",
        confidence=0.8,
        slots={},
        route="dynamic",
        reason_codes=[],
        family_candidates=[IntentFamily.ACTION],
    )
    m = apply_family_merge_policy(r, action_permission_granted=True)
    assert m.primary_family == IntentFamily.ACTION
    assert m.family_candidates == []


def test_merge_action_with_permission_retains_secondary_family() -> None:
    r = IntentClassificationResult(
        primary_family=IntentFamily.ACTION,
        primary_type="action.send",
        confidence=0.8,
        slots={},
        route="dynamic",
        reason_codes=[],
        family_candidates=[IntentFamily.RETRIEVAL],
    )
    m = apply_family_merge_policy(r, action_permission_granted=True)
    assert m.primary_family == IntentFamily.ACTION
    assert m.family_candidates == [IntentFamily.RETRIEVAL]


def test_merge_no_special_case_only_dedupes_candidates() -> None:
    r = IntentClassificationResult(
        primary_family=IntentFamily.PLANNING,
        primary_type="planning.goal",
        confidence=0.6,
        slots={},
        route="dynamic",
        reason_codes=["x"],
        family_candidates=[IntentFamily.PLANNING, IntentFamily.SYNTHESIS],
    )
    m = apply_family_merge_policy(r, action_permission_granted=False)
    assert m.primary_family == IntentFamily.PLANNING
    assert IntentFamily.PLANNING not in m.family_candidates
    assert IntentFamily.SYNTHESIS in m.family_candidates


def test_parse_json_accepts_families_alias() -> None:
    raw = json.dumps(
        {
            "primary_family": "synthesis",
            "primary_type": "synthesis.summary",
            "confidence": 0.8,
            "slots": {},
            "route": "dynamic",
            "reason_codes": ["llm_based"],
            "families": ["system"],
            "secondary_types": ["retrieval.weather"],
        }
    )
    r = parse_llm_classification_json(raw)
    assert r.family_candidates == [IntentFamily.SYSTEM]
    assert r.secondary_types == ["retrieval.weather"]
    m = apply_family_merge_policy(r, action_permission_granted=False)
    assert m.primary_family == IntentFamily.SYSTEM


def test_secondary_types_invalid_rejected() -> None:
    with pytest.raises(ValidationError):
        IntentClassificationResult(
            primary_family=IntentFamily.UNKNOWN,
            primary_type="unknown",
            confidence=0.1,
            slots={},
            route="dynamic",
            secondary_types=["Bad_Wire"],
        )
