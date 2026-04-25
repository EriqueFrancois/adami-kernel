# tests/test_intent_adaptive_rule_classifier.py
"""Tests for ``rule_classify_after_router`` (Step 3: rule-only tier)."""

from __future__ import annotations

import pytest

from adami_kernel.cortex.intent_adaptive import (
    RULE_CONFIDENCE_MAX,
    IntentFamily,
    IntentType,
    rule_classify_after_router,
)
from adami_kernel.cortex.intent_router import IntentSystemToken


@pytest.mark.parametrize(
    "router_tag,router_data",
    [
        ("SYSTEM_ACTION", IntentSystemToken.REPORT.value),
        ("SYSTEM_ACTION", "REPORT"),
        ("SYSTEM_ACTION", IntentSystemToken.MAINTAIN.value),
        ("DIRECT_ANSWER", "prefab text"),
    ],
)
def test_report_list_never_rule_classified_when_router_not_complex(
    router_tag: str, router_data: str
) -> None:
    """``/report list`` must stay a system route; rule tier must not emit SYNTHESIS."""
    assert (
        rule_classify_after_router(
            "/report list",
            router_tag=router_tag,
            router_data=router_data,
        )
        is None
    )


def test_report_list_suppressed_even_if_misrouted_as_complex() -> None:
    """Safety: explicit ``/report`` leader never gets rule relabeling (even if tag were wrong)."""
    assert (
        rule_classify_after_router(
            "/report list",
            router_tag="COMPLEX_TASK",
            router_data=None,
        )
        is None
    )


def test_complex_task_weather_maps_retrieval() -> None:
    r = rule_classify_after_router(
        "What is the weather in Paris tomorrow?",
        router_tag="COMPLEX_TASK",
        router_data=None,
    )
    assert r is not None
    assert r.primary_family == IntentFamily.RETRIEVAL
    assert r.primary_type == IntentType.RETRIEVAL_WEATHER
    assert r.confidence == RULE_CONFIDENCE_MAX
    assert r.route == "dynamic"
    assert "rule_hit_weather" in r.reason_codes


def test_complex_task_crypto_maps_retrieval() -> None:
    r = rule_classify_after_router(
        "Show BTC price and ETH trend",
        router_tag="COMPLEX_TASK",
        router_data=None,
    )
    assert r is not None
    assert r.primary_family == IntentFamily.RETRIEVAL
    assert r.primary_type == IntentType.RETRIEVAL_CRYPTO


def test_complex_task_synthesis_keyword() -> None:
    r = rule_classify_after_router(
        "请帮我调研竞品并写一份 executive summary",
        router_tag="COMPLEX_TASK",
        router_data=None,
    )
    assert r is not None
    assert r.primary_family == IntentFamily.SYNTHESIS
    assert r.primary_type == IntentType.SYNTHESIS_SUMMARY


def test_complex_task_no_match_returns_none() -> None:
    assert (
        rule_classify_after_router(
            "do something vague without keywords",
            router_tag="COMPLEX_TASK",
            router_data=None,
        )
        is None
    )
