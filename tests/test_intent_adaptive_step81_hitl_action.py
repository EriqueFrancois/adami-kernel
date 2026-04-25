# tests/test_intent_adaptive_step81_hitl_action.py
"""Step 8.1: ACTION templates + HitlHandler one-shot ack (no side effects until confirm)."""

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
)
from adami_kernel.cortex.intent_adaptive.outcomes import TemplateOutcome
from adami_kernel.cortex.intent_adaptive.template_registry import TemplateRegistry
from adami_kernel.orchestrator.hitl_handler import HitlHandler


def test_hitl_handler_grant_consume_roundtrip() -> None:
    bus = MagicMock()
    bus.publish = AsyncMock()
    hh = HitlHandler(bus, telegram_nerve=None, workflow_engine=None)
    hh.grant_intent_action_template_ack("7")
    assert hh.consume_intent_action_template_ack("7") is True
    assert hh.consume_intent_action_template_ack("7") is False


def test_hitl_prompt_sends_buttons_when_telegram_nerve_present() -> None:
    bus = MagicMock()
    nerve = MagicMock()
    nerve.send_interactive_buttons = AsyncMock()
    hh = HitlHandler(bus, telegram_nerve=nerve, workflow_engine=None)

    async def _run() -> None:
        await hh.prompt_intent_action_template_confirmation("42", "buy stocks now")

    asyncio.run(_run())
    nerve.send_interactive_buttons.assert_awaited_once()
    args, _kwargs = nerve.send_interactive_buttons.await_args
    assert args[0] == 42
    assert "intent_action_tpl:approve:42" in str(args[2])


def test_action_template_runs_after_hitl_pre_grant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED", True)
    monkeypatch.setattr(settings, "ADAMI_INTENT_ACTION_TEMPLATE_REQUIRES_CONFIRMATION", True)
    monkeypatch.setattr(settings, "ADAMI_INTENT_ACTION_PERMISSION_GRANTED", False)
    monkeypatch.setattr(settings, "ADAMI_INTENT_CLASSIFIER_MIN_CONFIDENCE", 0.5)

    action_cls = IntentClassificationResult(
        primary_family=IntentFamily.ACTION,
        primary_type="action.test",
        confidence=0.95,
        slots={},
        route="template",
        reason_codes=["test"],
    )

    exec_mock = AsyncMock(
        return_value=TemplateOutcome(
            reply_markdown="SIDE_EFFECT_OK",
            telemetry={},
            handoff_to_dynamic=False,
        )
    )

    class _H:
        async def match_score(self, classification):  # noqa: ANN001
            return 1.0 if classification.primary_type == "action.test" else 0.0

        async def execute(self, context):  # noqa: ANN001
            return await exec_mock()

    reg = TemplateRegistry(min_match_score=0.0)
    reg.register("action.test", _H())

    bus = MagicMock()
    bus.publish = AsyncMock()
    hh = HitlHandler(bus, telegram_nerve=None, workflow_engine=None)
    hh.grant_intent_action_template_ack("1")

    kernel = SimpleNamespace(
        active_sessions={},
        session_locks={},
        chat_locale_overrides={},
        bus=MagicMock(),
        memory=MagicMock(),
        router=MagicMock(call_llm=AsyncMock(return_value="{}")),
        toolbox=SimpleNamespace(web=None),
        immunity=MagicMock(),
        episodic_memory=None,
        planner=MagicMock(),
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
        _get_current_persona=lambda: "s81",
        hitl_handler=hh,
    )

    async def _run() -> tuple[bool, object]:
        dp = DecisionProcessor(kernel)  # type: ignore[arg-type]
        with (
            patch(
                "adami_kernel.cortex.intent_adaptive.rule_classifier.rule_classify_after_router",
                return_value=action_cls,
            ),
            patch(
                "adami_kernel.cortex.intent_adaptive.llm_classifier.maybe_llm_classify_with_settings",
                new=AsyncMock(return_value=None),
            ),
        ):
            return await dp._maybe_route_intent_adaptive(
                "do something",
                "1",
                "cli",
                "t-s81-pre",
                router_tag="COMPLEX_TASK",
                router_data=None,
                trace_span=None,
            )

    handled, _meta = asyncio.run(_run())
    assert handled is True
    exec_mock.assert_awaited_once()
    assert "SIDE_EFFECT_OK" in str(kernel._send_reply.await_args[0][1])
