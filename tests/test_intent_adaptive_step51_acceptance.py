# tests/test_intent_adaptive_step51_acceptance.py
"""
Step 5.1 acceptance tests (see ``docs/intent_adaptive_pipeline.md`` § Step 5.1 — Acceptance test plan).
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from adami_kernel.config import settings
from adami_kernel.cortex.decision_processor import DecisionProcessor
from adami_kernel.cortex.intent_adaptive import (
    ATTR_INTENT_CONFIDENCE,
    ATTR_INTENT_FAMILY,
    ATTR_INTENT_ROUTE,
    ATTR_INTENT_TYPE,
    IntentClassificationResult,
    IntentFamily,
    intent_span_attributes_dict,
    record_intent_classification_on_span,
)
from adami_kernel.cortex.intent_adaptive.outcomes import TemplateOutcome
from adami_kernel.cortex.intent_adaptive.template_registry import TemplateRegistry
from adami_kernel.i18n.catalog import default_translator

_REPO = Path(__file__).resolve().parents[1]
_README = _REPO / "README.md"
_LOCALES = _REPO / "src" / "adami_kernel" / "i18n" / "locales"


class _WeatherTemplate:
    async def match_score(self, classification):  # noqa: ANN001
        return 1.0 if classification.primary_type == "retrieval.weather" else 0.0

    async def execute(self, context):  # noqa: ANN001
        _ = context
        return TemplateOutcome(
            reply_markdown="S51_ACCEPT_WEATHER",
            telemetry={},
            handoff_to_dynamic=False,
        )


def _kernel_with_weather_registry(reg: TemplateRegistry) -> SimpleNamespace:
    planner = MagicMock()
    planner.plan_and_execute = AsyncMock(return_value="PLAN_OK")
    router = MagicMock()
    router.call_llm = AsyncMock(side_effect=AssertionError("LLM must not run for strong rule tier"))
    return SimpleNamespace(
        active_sessions={},
        session_locks={},
        chat_locale_overrides={},
        bus=MagicMock(),
        memory=MagicMock(),
        router=router,
        toolbox=SimpleNamespace(web_search=None),
        immunity=MagicMock(),
        episodic_memory=None,
        planner=planner,
        intent_router=MagicMock(),
        intent_template_registry=reg,
        skill_router=None,
        evolution_engine=MagicMock(),
        prompt_builder=MagicMock(),
        skill_optimizer=None,
        second_brain=None,
        telegram_nerve=None,
        discord_nerve=None,
        proprioception=None,
        _send_reply=AsyncMock(),
        _handle_system_action=AsyncMock(),
        _parse_decision=MagicMock(return_value=("THINK", {})),
        _get_current_persona=lambda: "s51",
    )


# --- S51-A. Span keys ---


def test_s51a1_attr_constants_match_otel_names() -> None:
    assert ATTR_INTENT_FAMILY == "intent.family"
    assert ATTR_INTENT_TYPE == "intent.type"
    assert ATTR_INTENT_CONFIDENCE == "intent.confidence"
    assert ATTR_INTENT_ROUTE == "intent.route"


# --- S51-B. Span bridge ---


def test_s51b1_intent_span_attributes_dict_matches_keys() -> None:
    r = IntentClassificationResult(
        primary_family=IntentFamily.RETRIEVAL,
        primary_type="retrieval.weather",
        confidence=0.6,
        slots={},
        route="dynamic",
    )
    d = intent_span_attributes_dict(r)
    assert d[ATTR_INTENT_FAMILY] == "retrieval"
    assert d[ATTR_INTENT_TYPE] == "retrieval.weather"
    assert d[ATTR_INTENT_CONFIDENCE] == 0.6
    assert d[ATTR_INTENT_ROUTE] == "dynamic"


def test_s51b2_record_invokes_set_attribute_four_times() -> None:
    span = MagicMock()
    r = IntentClassificationResult(
        primary_family=IntentFamily.PLANNING,
        primary_type="planning.goal",
        confidence=0.55,
        slots={},
        route="template",
    )
    record_intent_classification_on_span(span, r)
    span.set_attribute.assert_any_call(ATTR_INTENT_FAMILY, "planning")
    span.set_attribute.assert_any_call(ATTR_INTENT_TYPE, "planning.goal")
    span.set_attribute.assert_any_call(ATTR_INTENT_CONFIDENCE, 0.55)
    span.set_attribute.assert_any_call(ATTR_INTENT_ROUTE, "template")


def test_s51b3_record_swallows_setter_errors() -> None:
    span = MagicMock()

    def boom(*_a, **_k):
        raise RuntimeError("backend")

    span.set_attribute = boom
    r = IntentClassificationResult(
        primary_family=IntentFamily.UNKNOWN,
        primary_type="unknown",
        confidence=0.0,
        slots={},
        route="dynamic",
    )
    record_intent_classification_on_span(span, r)


# --- S51-C. Log audit (grep ``[intent_adaptive]``) ---


def test_s51c1_debug_log_contains_prefix_and_route(
    caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    reg = TemplateRegistry(min_match_score=0.0)
    reg.register("retrieval.weather", _WeatherTemplate())
    kernel = _kernel_with_weather_registry(reg)
    monkeypatch.setattr(settings, "ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED", True)
    trace_span = MagicMock()

    async def _run() -> None:
        dp = DecisionProcessor(kernel)  # type: ignore[arg-type]
        await dp._dispatch_complex_task(
            "What is the weather in Tokyo?",
            "1",
            "telegram",
            "trace-s51c",
            router_data=None,
            trace_span=trace_span,
        )

    with caplog.at_level(logging.DEBUG, logger="AdamI-DecisionProcessor"):
        asyncio.run(_run())

    hits = [r.message for r in caplog.records if "[intent_adaptive]" in r.message]
    assert hits
    assert any("route=" in m for m in hits)
    trace_span.set_attribute.assert_called()


# --- S51-D. i18n ---


@pytest.mark.parametrize("locale", ["en", "zh-Hans"])
@pytest.mark.parametrize(
    "key",
    [
        "doc.intent_adaptive.step51_observability",
        "doc.operator.intent_adaptive_grep",
    ],
)
def test_s51d1_catalog_keys_non_empty(locale: str, key: str) -> None:
    path = _LOCALES / locale / "common.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert key in data and str(data[key]).strip()


def test_s51d2_bilingual_doc_strings_differ() -> None:
    tr = default_translator()
    for key in (
        "doc.intent_adaptive.step51_observability",
        "doc.operator.intent_adaptive_grep",
    ):
        assert tr.t(key, locale="en") != tr.t(key, locale="zh-Hans"), key


# --- S51-E. README ---


def test_s51e_readme_observability_signals() -> None:
    text = _README.read_text(encoding="utf-8")
    assert "doc.intent_adaptive.step51_observability" in text
    assert "AdamI-DecisionProcessor" in text
    assert "[intent_adaptive]" in text
    assert "intent.family" in text


# --- S51-F. Package surface ---


def test_s51f_telemetry_exports_on_package() -> None:
    import adami_kernel.cortex.intent_adaptive as ia

    for name in (
        "ATTR_INTENT_CONFIDENCE",
        "ATTR_INTENT_FAMILY",
        "ATTR_INTENT_ROUTE",
        "ATTR_INTENT_TYPE",
        "intent_span_attributes_dict",
        "record_intent_classification_on_span",
    ):
        assert name in ia.__all__
        assert hasattr(ia, name)
