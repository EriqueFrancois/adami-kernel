# tests/test_intent_adaptive_step3_acceptance.py
"""
Step 3 acceptance tests for ``rule_classify_after_router`` (see
``docs/intent_adaptive_pipeline.md`` § Step 3 — Acceptance test plan).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import adami_kernel.cortex.intent_adaptive as ia
from adami_kernel.cortex.intent_adaptive import (
    RULE_CONFIDENCE_MAX,
    IntentFamily,
    IntentType,
    rule_classify_after_router,
)

_REPO = Path(__file__).resolve().parents[1]
_README = _REPO / "README.md"
_LOCALES = _REPO / "src" / "adami_kernel" / "i18n" / "locales"
_INTENT_ROUTER = _REPO / "src" / "adami_kernel" / "cortex" / "intent_router.py"


# --- S3-A: Public API ---


def test_s3a_exports_on_package() -> None:
    assert "rule_classify_after_router" in ia.__all__
    assert "RULE_CONFIDENCE_MAX" in ia.__all__
    assert ia.RULE_CONFIDENCE_MAX == 0.6
    assert callable(ia.rule_classify_after_router)


# --- S3-B: Bounded confidence and route shape ---


@pytest.mark.parametrize(
    "task",
    [
        "hello",
        "weather in Berlin",
        "ETH price now",
        "roadmap for Q2",
        "write a research summary of competitors",
    ],
)
def test_s3b_non_none_results_bounded_and_dynamic(task: str) -> None:
    r = rule_classify_after_router(task, router_tag="COMPLEX_TASK", router_data=None)
    assert r is not None
    assert r.confidence <= RULE_CONFIDENCE_MAX
    assert r.confidence == RULE_CONFIDENCE_MAX
    assert r.route == "dynamic"
    assert "rule_based" in r.reason_codes


# --- S3-C: Non-COMPLEX tags always opt out ---


@pytest.mark.parametrize("tag", ["SYSTEM_ACTION", "DIRECT_ANSWER", "UNKNOWN_TAG", ""])
def test_s3c_only_complex_task_tag_invokes_rules(tag: str) -> None:
    r = rule_classify_after_router(
        "weather in Tokyo",
        router_tag=tag,
        router_data=None,
    )
    assert r is None


# --- S3-D: `/report` leader guard ---


@pytest.mark.parametrize(
    "line",
    ["/report", "/report list", "/REPORT show daily"],
)
def test_s3d_report_leader_never_classified(line: str) -> None:
    assert rule_classify_after_router(line, router_tag="COMPLEX_TASK", router_data=None) is None


# --- S3-E: Heuristic precedence (weather before crypto in pipeline) ---


def test_s3e_weather_precedes_crypto_when_both_keywords() -> None:
    r = rule_classify_after_router(
        "BTC weather correlation study",
        router_tag="COMPLEX_TASK",
        router_data=None,
    )
    assert r is not None
    assert r.primary_type == IntentType.RETRIEVAL_WEATHER


# --- S3-F / S3-G: Docs and i18n ---


def test_s3f_bilingual_rule_tier_doc_strings() -> None:
    from adami_kernel.i18n.catalog import default_translator

    tr = default_translator()
    a = tr.t("doc.intent_adaptive.rule_tier", locale="en")
    b = tr.t("doc.intent_adaptive.rule_tier", locale="zh-Hans")
    assert a.strip() and b.strip()
    assert a != b


@pytest.mark.parametrize("locale", ["en", "zh-Hans"])
def test_s3f_rule_tier_key_present(locale: str) -> None:
    path = _LOCALES / locale / "common.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    k = "doc.intent_adaptive.rule_tier"
    assert k in data and str(data[k]).strip()


def test_s3g_readme_mentions_rule_tier_and_phase1() -> None:
    text = _README.read_text(encoding="utf-8")
    assert "doc.intent_adaptive.rule_tier" in text
    assert "Phase 1" in text or "rule_classify_after_router" in text


def test_s3g_intent_router_docstring_points_to_intent_adaptive() -> None:
    src = _INTENT_ROUTER.read_text(encoding="utf-8")
    assert "intent_adaptive" in src
    assert "rule_classify_after_router" in src


# --- S3-H: Empty / whitespace-only tasks ---


@pytest.mark.parametrize("task", ["", "   ", "\n\t"])
def test_s3h_empty_task_yields_none(task: str) -> None:
    assert rule_classify_after_router(task, router_tag="COMPLEX_TASK", router_data=None) is None


# --- S3-I: Greeting is full-line only ---


def test_s3i_greeting_not_partial_line() -> None:
    assert (
        rule_classify_after_router(
            "hello and more text after",
            router_tag="COMPLEX_TASK",
            router_data=None,
        )
        is None
    )


def test_s3i_greeting_hits_for_plain_hello() -> None:
    r = rule_classify_after_router("hello", router_tag="COMPLEX_TASK", router_data=None)
    assert r is not None
    assert r.primary_family == IntentFamily.CONVERSATION
    assert r.primary_type == IntentType.CONVERSATION_GREETING
