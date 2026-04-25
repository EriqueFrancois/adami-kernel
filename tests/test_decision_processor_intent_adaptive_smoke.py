# tests/test_decision_processor_intent_adaptive_smoke.py
"""Step 5 smoke: DecisionProcessor tiered intent path vs Planner fallback."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from adami_kernel.config import settings
from adami_kernel.cortex.decision_processor import DecisionProcessor
from adami_kernel.cortex.intent_adaptive.outcomes import TemplateOutcome
from adami_kernel.cortex.intent_adaptive.template_registry import TemplateRegistry


class _WeatherTemplate:
    async def match_score(self, classification):  # noqa: ANN001
        return 1.0 if classification.primary_type == "retrieval.weather" else 0.0

    async def execute(self, context):  # noqa: ANN001
        _ = context
        return TemplateOutcome(
            reply_markdown="SMOKE_TEMPLATE_WEATHER",
            telemetry={"smoke": True},
            handoff_to_dynamic=False,
        )


def _make_kernel(*, registry: TemplateRegistry) -> SimpleNamespace:
    planner = MagicMock()
    planner.plan_and_execute = AsyncMock(return_value="PLANNER_RAN")

    router = MagicMock()

    async def _llm_guard(*_a, **_k):
        raise AssertionError("call_llm should not run when rule tier is strong enough")

    router.call_llm = AsyncMock(side_effect=_llm_guard)

    toolbox = SimpleNamespace(web_search=None)

    send = AsyncMock()

    return SimpleNamespace(
        active_sessions={},
        session_locks={},
        chat_locale_overrides={},
        bus=MagicMock(),
        memory=MagicMock(),
        router=router,
        toolbox=toolbox,
        immunity=MagicMock(),
        episodic_memory=None,
        planner=planner,
        intent_router=MagicMock(),
        intent_template_registry=registry,
        skill_router=None,
        evolution_engine=MagicMock(),
        prompt_builder=MagicMock(),
        skill_optimizer=None,
        second_brain=None,
        telegram_nerve=None,
        discord_nerve=None,
        proprioception=None,
        _send_reply=send,
        _handle_system_action=AsyncMock(),
        _parse_decision=MagicMock(return_value=("THINK", {})),
        _get_current_persona=lambda: "smoke",
    )


@pytest.mark.parametrize("pipeline_on", [True, False])
def test_template_vs_planner_by_pipeline_flag(
    monkeypatch: pytest.MonkeyPatch, pipeline_on: bool
) -> None:
    reg = TemplateRegistry(min_match_score=0.0)
    reg.register("retrieval.weather", _WeatherTemplate())
    kernel = _make_kernel(registry=reg)
    monkeypatch.setattr(settings, "ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED", pipeline_on)

    async def _run() -> None:
        dp = DecisionProcessor(kernel)  # type: ignore[arg-type]
        await dp._dispatch_complex_task(
            "What is the weather in Shanghai tomorrow?",
            "1",
            "telegram",
            "trace-smoke-weather",
            router_data=None,
        )

    asyncio.run(_run())

    if pipeline_on:
        kernel.planner.plan_and_execute.assert_not_called()
        kernel._send_reply.assert_awaited()
        args = kernel._send_reply.await_args
        assert args is not None
        assert "SMOKE_TEMPLATE_WEATHER" in str(args[0][1])
    else:
        kernel.planner.plan_and_execute.assert_awaited_once()
        kernel._send_reply.assert_awaited()


def test_unmatched_rule_goes_to_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    reg = TemplateRegistry(min_match_score=0.0)
    reg.register("retrieval.weather", _WeatherTemplate())
    kernel = _make_kernel(registry=reg)
    monkeypatch.setattr(settings, "ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED", True)
    kernel.router.call_llm = AsyncMock(return_value="{}")

    async def _run() -> None:
        dp = DecisionProcessor(kernel)  # type: ignore[arg-type]
        await dp._dispatch_complex_task(
            "qqqqzzz_unique_no_rule_match_zzzz",
            "1",
            "telegram",
            "trace-smoke-fallback",
            router_data=None,
        )

    asyncio.run(_run())

    kernel.planner.plan_and_execute.assert_awaited_once()
