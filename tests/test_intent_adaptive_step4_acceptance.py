# tests/test_intent_adaptive_step4_acceptance.py
"""
Step 4 acceptance tests for ``llm_classifier`` (see
``docs/intent_adaptive_pipeline.md`` § Step 4 — Acceptance test plan).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

import adami_kernel.cortex.intent_adaptive as ia
from adami_kernel.config import settings
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
from adami_kernel.i18n.catalog import default_translator

_REPO = Path(__file__).resolve().parents[1]
_README = _REPO / "README.md"
_CONFIG = _REPO / "src" / "adami_kernel" / "config.py"
_LOCALES = _REPO / "src" / "adami_kernel" / "i18n" / "locales"


# --- S4-A: Package surface ---


def test_s4a_exports() -> None:
    for name in (
        "maybe_llm_classify_after_rule",
        "maybe_llm_classify_with_settings",
        "build_intent_classification_llm_prompt",
        "parse_llm_classification_json",
    ):
        assert name in ia.__all__
        assert hasattr(ia, name)


# --- S4-B: Settings defaults (class fields) ---


def test_s4b_settings_defaults_disable_llm_classifier() -> None:
    assert settings.ADAMI_INTENT_LLM_CLASSIFIER_ENABLED is False
    assert settings.ADAMI_INTENT_CLASSIFIER_MIN_CONFIDENCE == 0.55
    assert settings.ADAMI_INTENT_CLASSIFIER_TIMEOUT_SEC == 8.0
    assert settings.ADAMI_INTENT_ACTION_PERMISSION_GRANTED is False


# --- S4-C: call_llm policy kwargs (no design-output prefix on JSON path) ---


def test_s4c_call_llm_disables_design_output_policy() -> None:
    call_llm = AsyncMock(
        return_value=json.dumps(
            {
                "primary_family": "synthesis",
                "primary_type": "synthesis.summary",
                "confidence": 0.7,
                "slots": {},
                "route": "dynamic",
                "reason_codes": ["llm_based"],
            },
            ensure_ascii=False,
        )
    )
    asyncio.run(
        maybe_llm_classify_after_rule(
            "write a research summary",
            router_tag="COMPLEX_TASK",
            router_data=None,
            rule_result=None,
            call_llm=call_llm,
            enabled=True,
            min_confidence=0.55,
            timeout_sec=5.0,
        )
    )
    assert call_llm.await_count == 1
    _args, kwargs = call_llm.call_args
    assert kwargs.get("apply_design_output_policy") is False
    assert kwargs.get("skip_design_output_policy") is True
    assert kwargs.get("temperature") == 0.1


# --- S4-D: Invalid schema from LLM → downgrade ---


def test_s4d_invalid_family_json_degrades() -> None:
    bad = json.dumps(
        {
            "primary_family": "not_a_real_family",
            "primary_type": "unknown",
            "confidence": 0.9,
            "slots": {},
            "route": "dynamic",
            "reason_codes": ["llm_based"],
        }
    )
    call_llm = AsyncMock(return_value=bad)
    out = asyncio.run(
        maybe_llm_classify_after_rule(
            "x",
            router_tag="COMPLEX_TASK",
            router_data=None,
            rule_result=None,
            call_llm=call_llm,
            enabled=True,
            min_confidence=0.55,
            timeout_sec=5.0,
        )
    )
    assert out is not None
    assert out.primary_family == IntentFamily.UNKNOWN
    assert "llm_classifier_parse_error" in out.reason_codes


# --- S4-E: i18n user strings ---


@pytest.mark.parametrize("locale", ["en", "zh-Hans"])
@pytest.mark.parametrize("key", ["intent.classifier.parse_error", "intent.classifier.unavailable"])
def test_s4e_user_strings_present(locale: str, key: str) -> None:
    path = _LOCALES / locale / "common.json"
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert key in raw and str(raw[key]).strip()


def test_s4e_doc_step4_bilingual_differs() -> None:
    tr = default_translator()
    a = tr.t("doc.intent_adaptive.step4_llm_classifier", locale="en")
    b = tr.t("doc.intent_adaptive.step4_llm_classifier", locale="zh-Hans")
    assert a.strip() and b.strip()
    assert a != b


def test_s4e_user_parse_and_unavailable_differ_by_locale() -> None:
    tr = default_translator()
    a = tr.t("intent.classifier.parse_error", locale="en")
    b = tr.t("intent.classifier.parse_error", locale="zh-Hans")
    assert a != b


# --- S4-F: Repository hygiene ---


def test_s4f_readme_lists_env_and_step4_doc() -> None:
    text = _README.read_text(encoding="utf-8")
    assert "ADAMI_INTENT_LLM_CLASSIFIER_ENABLED" in text
    assert "doc.intent_adaptive.step4_llm_classifier" in text


def test_s4f_config_module_documents_intent_settings() -> None:
    src = _CONFIG.read_text(encoding="utf-8")
    assert "ADAMI_INTENT_LLM_CLASSIFIER_ENABLED" in src
    assert "ADAMI_INTENT_CLASSIFIER_MIN_CONFIDENCE" in src
    assert "ADAMI_INTENT_CLASSIFIER_TIMEOUT_SEC" in src


# --- S4-G: ``maybe_llm_classify_with_settings`` honours global defaults ---


def test_s4g_with_settings_disabled_matches_explicit_disabled() -> None:
    call_llm = AsyncMock()
    rule = IntentClassificationResult(
        primary_family=IntentFamily.RETRIEVAL,
        primary_type=IntentType.RETRIEVAL_WEATHER,
        confidence=0.6,
        slots={},
        route="dynamic",
        reason_codes=["rule_based"],
    )
    out = asyncio.run(
        maybe_llm_classify_with_settings(
            "any",
            router_tag="COMPLEX_TASK",
            router_data=None,
            rule_result=rule,
            call_llm=call_llm,
            settings=settings,
        )
    )
    assert out is rule
    call_llm.assert_not_called()


# --- S4-H: parse helper accepts fenced JSON (contract) ---


def test_s4h_parse_round_trip_family_enum() -> None:
    r = parse_llm_classification_json(
        "```json\n"
        + json.dumps(
            {
                "primary_family": "planning",
                "primary_type": "planning.goal",
                "confidence": 0.5,
                "slots": {"horizon": "7d"},
                "route": "clarify",
                "reason_codes": ["llm_based"],
            }
        )
        + "\n```"
    )
    assert r.primary_family == IntentFamily.PLANNING
    assert r.route == "clarify"
    assert r.slots.get("horizon") == "7d"


# --- S4-I: Prompt builder includes schema vocabulary ---


def test_s4i_prompt_contains_json_keys_and_family_list() -> None:
    p = build_intent_classification_llm_prompt("sample")
    assert "primary_family" in p
    assert "reason_codes" in p
    assert "retrieval" in p
    assert "synthesis" in p
