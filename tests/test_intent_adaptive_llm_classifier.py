# tests/test_intent_adaptive_llm_classifier.py
"""Tests for ``llm_classifier`` (Step 4: optional LLM JSON classification)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from adami_kernel.cortex.intent_adaptive import (
    IntentClassificationResult,
    IntentFamily,
    IntentType,
    maybe_llm_classify_after_rule,
    maybe_llm_classify_with_settings,
    parse_llm_classification_json,
)
from adami_kernel.cortex.intent_adaptive.llm_classifier import (
    build_intent_classification_llm_prompt,
)


def _valid_payload() -> str:
    return json.dumps(
        {
            "primary_family": "retrieval",
            "primary_type": "retrieval.weather",
            "confidence": 0.88,
            "slots": {"city": "Oslo"},
            "route": "dynamic",
            "reason_codes": ["llm_based", "probe"],
        },
        ensure_ascii=False,
    )


def test_parse_llm_classification_json_plain() -> None:
    r = parse_llm_classification_json(_valid_payload())
    assert r.primary_family == IntentFamily.RETRIEVAL
    assert r.primary_type == "retrieval.weather"
    assert r.confidence == 0.88
    assert r.slots.get("city") == "Oslo"


def test_parse_llm_classification_json_fenced() -> None:
    raw = "```json\n" + _valid_payload() + "\n```"
    r = parse_llm_classification_json(raw)
    assert r.primary_type == "retrieval.weather"


def test_parse_llm_classification_json_invalid() -> None:
    with pytest.raises(json.JSONDecodeError):
        parse_llm_classification_json("not-json {{{")


def test_build_prompt_lists_families_and_types() -> None:
    p = build_intent_classification_llm_prompt("hello world")
    assert "primary_family" in p
    assert "retrieval" in p
    assert "retrieval.weather" in p or "unknown" in p
    assert "hello world" in p


def test_maybe_llm_disabled_returns_rule_unchanged() -> None:
    async def boom(*a: object, **kw: object) -> str:
        raise AssertionError("call_llm must not run when disabled")

    rule = IntentClassificationResult(
        primary_family=IntentFamily.RETRIEVAL,
        primary_type=IntentType.RETRIEVAL_WEATHER,
        confidence=0.6,
        slots={},
        route="dynamic",
        reason_codes=["rule_based"],
    )
    out = asyncio.run(
        maybe_llm_classify_after_rule(
            "any",
            router_tag="COMPLEX_TASK",
            router_data=None,
            rule_result=rule,
            call_llm=boom,
            enabled=False,
            min_confidence=0.55,
            timeout_sec=8.0,
        )
    )
    assert out is rule


def test_maybe_llm_skips_when_strong_rule() -> None:
    call_llm = AsyncMock(return_value=_valid_payload())
    rule = IntentClassificationResult(
        primary_family=IntentFamily.RETRIEVAL,
        primary_type=IntentType.RETRIEVAL_WEATHER,
        confidence=0.6,
        slots={},
        route="dynamic",
        reason_codes=["rule_based"],
    )
    out = asyncio.run(
        maybe_llm_classify_after_rule(
            "x",
            router_tag="COMPLEX_TASK",
            router_data=None,
            rule_result=rule,
            call_llm=call_llm,
            enabled=True,
            min_confidence=0.55,
            timeout_sec=8.0,
        )
    )
    assert out is rule
    call_llm.assert_not_called()


def test_maybe_llm_calls_on_weak_rule() -> None:
    call_llm = AsyncMock(return_value=_valid_payload())
    rule = IntentClassificationResult(
        primary_family=IntentFamily.RETRIEVAL,
        primary_type=IntentType.RETRIEVAL_WEATHER,
        confidence=0.5,
        slots={},
        route="dynamic",
        reason_codes=["rule_based"],
    )
    out = asyncio.run(
        maybe_llm_classify_after_rule(
            "x",
            router_tag="COMPLEX_TASK",
            router_data=None,
            rule_result=rule,
            call_llm=call_llm,
            enabled=True,
            min_confidence=0.55,
            timeout_sec=8.0,
        )
    )
    assert out is not None
    assert out.primary_type == "retrieval.weather"
    assert "llm_based" in out.reason_codes
    call_llm.assert_called_once()


def test_maybe_llm_parse_error_degrades() -> None:
    call_llm = AsyncMock(return_value="NOT JSON")
    out = asyncio.run(
        maybe_llm_classify_after_rule(
            "x",
            router_tag="COMPLEX_TASK",
            router_data=None,
            rule_result=None,
            call_llm=call_llm,
            enabled=True,
            min_confidence=0.55,
            timeout_sec=8.0,
        )
    )
    assert out is not None
    assert out.primary_family == IntentFamily.UNKNOWN
    assert "llm_classifier_parse_error" in out.reason_codes


def test_maybe_llm_timeout_degrades() -> None:
    async def slow(*a: object, **kw: object) -> str:
        await asyncio.sleep(2.0)
        return _valid_payload()

    out = asyncio.run(
        maybe_llm_classify_after_rule(
            "x",
            router_tag="COMPLEX_TASK",
            router_data=None,
            rule_result=None,
            call_llm=slow,
            enabled=True,
            min_confidence=0.55,
            timeout_sec=0.02,
        )
    )
    assert out is not None
    assert out.primary_family == IntentFamily.UNKNOWN
    assert "llm_classifier_timeout" in out.reason_codes


def test_maybe_llm_skips_for_non_complex_router_tag() -> None:
    call_llm = AsyncMock(return_value=_valid_payload())
    out = asyncio.run(
        maybe_llm_classify_after_rule(
            "x",
            router_tag="SYSTEM_ACTION",
            router_data="REPORT",
            rule_result=None,
            call_llm=call_llm,
            enabled=True,
            min_confidence=0.55,
            timeout_sec=8.0,
        )
    )
    assert out is None
    call_llm.assert_not_called()


def test_maybe_llm_classify_with_settings_respects_flags() -> None:
    call_llm = AsyncMock(return_value=_valid_payload())
    cfg = SimpleNamespace(
        ADAMI_INTENT_LLM_CLASSIFIER_ENABLED=False,
        ADAMI_INTENT_CLASSIFIER_MIN_CONFIDENCE=0.99,
        ADAMI_INTENT_CLASSIFIER_TIMEOUT_SEC=1.0,
    )
    out = asyncio.run(
        maybe_llm_classify_with_settings(
            "hi",
            router_tag="COMPLEX_TASK",
            router_data=None,
            rule_result=None,
            call_llm=call_llm,
            settings=cfg,
        )
    )
    assert out is None
    call_llm.assert_not_called()
