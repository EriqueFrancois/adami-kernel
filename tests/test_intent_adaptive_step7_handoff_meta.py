# tests/test_intent_adaptive_step7_handoff_meta.py
"""Step 7: Planner receives optional ``intent_adaptive_meta`` on adaptive fallback (telemetry)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from adami_kernel.config import settings
from adami_kernel.cortex.decision_processor import DecisionProcessor
from adami_kernel.cortex.intent_adaptive.models import (
    IntentClassificationResult,
    IntentFamily,
    IntentType,
)
from adami_kernel.cortex.intent_adaptive.outcomes import TemplateOutcome
from adami_kernel.cortex.intent_adaptive.template_registry import TemplateRegistry


class _WeatherTemplate:
    async def match_score(self, classification):  # noqa: ANN001
        return 1.0 if classification.primary_type == "retrieval.weather" else 0.0

    async def execute(self, context):  # noqa: ANN001
        _ = context
        return TemplateOutcome(
            reply_markdown="STEP7_WEATHER_BODY",
            telemetry={"step7": True},
            handoff_to_dynamic=False,
        )


def _kernel_with_registry(reg: TemplateRegistry) -> SimpleNamespace:
    planner = MagicMock()
    planner.plan_and_execute = AsyncMock(return_value="PLANNER_OK")

    router = MagicMock()
    router.call_llm = AsyncMock(return_value="{}")

    return SimpleNamespace(
        active_sessions={},
        session_locks={},
        chat_locale_overrides={},
        bus=MagicMock(),
        memory=MagicMock(),
        router=router,
        toolbox=SimpleNamespace(web=None),
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
        _get_current_persona=lambda: "step7",
    )


def test_step7_planner_gets_meta_when_pipeline_on_and_below_template_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Rule hit ``route=dynamic`` but confidence below min → same Planner path + handoff meta."""
    reg = TemplateRegistry(min_match_score=0.0)
    reg.register("retrieval.weather", _WeatherTemplate())
    kernel = _kernel_with_registry(reg)
    monkeypatch.setattr(settings, "ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED", True)
    monkeypatch.setattr(settings, "ADAMI_INTENT_ADAPTIVE_FALLBACK_NOTICE", False)
    monkeypatch.setattr(settings, "ADAMI_INTENT_CLASSIFIER_MIN_CONFIDENCE", 0.99)

    async def _run() -> None:
        dp = DecisionProcessor(kernel)  # type: ignore[arg-type]
        await dp._dispatch_complex_task(
            "hello",
            "1",
            "telegram",
            "trace-step7-meta",
            router_data=None,
            trace_span=None,
        )

    asyncio.run(_run())

    kernel.planner.plan_and_execute.assert_awaited_once()
    kw = kernel.planner.plan_and_execute.await_args.kwargs
    assert "intent_adaptive_meta" in kw
    meta = kw["intent_adaptive_meta"]
    assert meta["handoff_kind"] == "intent_adaptive_planner_fallback"
    assert meta["route"] == "dynamic"
    assert meta.get("dynamic_or_unknown_tail") is True
    assert meta["handoff_reason"] == "no_template_or_below_min_confidence"


def test_step7_planner_no_meta_when_pipeline_off(monkeypatch: pytest.MonkeyPatch) -> None:
    reg = TemplateRegistry(min_match_score=0.0)
    reg.register("retrieval.weather", _WeatherTemplate())
    kernel = _kernel_with_registry(reg)
    monkeypatch.setattr(settings, "ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED", False)

    async def _run() -> None:
        dp = DecisionProcessor(kernel)  # type: ignore[arg-type]
        await dp._dispatch_complex_task(
            "hello",
            "1",
            "telegram",
            "trace-step7-off",
            router_data=None,
            trace_span=None,
        )

    asyncio.run(_run())

    kernel.planner.plan_and_execute.assert_awaited_once()
    kw = kernel.planner.plan_and_execute.await_args.kwargs
    assert "intent_adaptive_meta" not in kw


def test_step7_unknown_family_sets_tail_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """``primary_family=UNKNOWN`` adds ``dynamic_or_unknown_tail`` even when route is template."""
    reg = TemplateRegistry(min_match_score=0.0)
    reg.register("retrieval.weather", _WeatherTemplate())
    kernel = _kernel_with_registry(reg)

    fake_cls = IntentClassificationResult(
        primary_family=IntentFamily.UNKNOWN,
        primary_type=IntentType.UNKNOWN,
        confidence=0.99,
        slots={},
        route="template",
        reason_codes=["test_unknown"],
    )

    monkeypatch.setattr(settings, "ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED", True)
    monkeypatch.setattr(settings, "ADAMI_INTENT_LLM_CLASSIFIER_ENABLED", True)
    monkeypatch.setattr(settings, "ADAMI_INTENT_CLASSIFIER_MIN_CONFIDENCE", 0.5)

    with patch(
        "adami_kernel.cortex.intent_adaptive.llm_classifier.maybe_llm_classify_with_settings",
        new=AsyncMock(return_value=fake_cls),
    ):

        async def _run() -> tuple[bool, object]:
            dp = DecisionProcessor(kernel)  # type: ignore[arg-type]
            return await dp._maybe_route_intent_adaptive(
                "qqqq_unique_no_rule_zzzz",
                "1",
                "telegram",
                "t-unknown",
                router_tag="COMPLEX_TASK",
                router_data=None,
                trace_span=None,
            )

        handled, meta = asyncio.run(_run())

    assert handled is False
    assert meta is not None
    assert meta["primary_family"] == "unknown"
    assert meta.get("dynamic_or_unknown_tail") is True


def test_step7_low_confidence_still_runs_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: Planner still invoked and reply path does not crash."""
    reg = TemplateRegistry(min_match_score=0.0)
    reg.register("retrieval.weather", _WeatherTemplate())
    kernel = _kernel_with_registry(reg)
    monkeypatch.setattr(settings, "ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED", True)
    monkeypatch.setattr(settings, "ADAMI_INTENT_CLASSIFIER_MIN_CONFIDENCE", 0.99)

    async def _run() -> None:
        dp = DecisionProcessor(kernel)  # type: ignore[arg-type]
        await dp._dispatch_complex_task(
            "What is the weather in Paris tomorrow?",
            "42",
            "telegram",
            "trace-step7-weather-lowconf",
            router_data=None,
            trace_span=None,
        )

    asyncio.run(_run())

    kernel.planner.plan_and_execute.assert_awaited_once()
    assert "intent_adaptive_meta" in kernel.planner.plan_and_execute.await_args.kwargs
    kernel._send_reply.assert_awaited()
