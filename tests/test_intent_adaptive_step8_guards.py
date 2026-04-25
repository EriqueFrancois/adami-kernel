# tests/test_intent_adaptive_step8_guards.py
"""Step 8: intent adaptive timeouts, ACTION template gate, session_lock stress."""

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
from adami_kernel.nexus.event import AdamiEvent, EventPriority


def test_s8_settings_defaults() -> None:
    assert float(settings.ADAMI_INTENT_ADAPTIVE_LLM_PHASE_TIMEOUT_SEC) >= 1.0
    assert float(settings.ADAMI_INTENT_TEMPLATE_EXECUTE_TIMEOUT_SEC) >= 1.0
    assert settings.ADAMI_INTENT_ACTION_TEMPLATE_REQUIRES_CONFIRMATION is True


class _ActionHandler:
    async def match_score(self, classification):  # noqa: ANN001
        return 1.0 if classification.primary_type == "action.test" else 0.0

    async def execute(self, context):  # noqa: ANN001
        return TemplateOutcome(
            reply_markdown="ACTION_BODY_SHOULD_NOT_SEND",
            telemetry={},
            handoff_to_dynamic=False,
        )


class _SlowHandler:
    async def match_score(self, classification):  # noqa: ANN001
        return 1.0 if classification.primary_type == "retrieval.weather" else 0.0

    async def execute(self, context):  # noqa: ANN001
        await asyncio.sleep(100.0)
        return TemplateOutcome(reply_markdown="slow", telemetry={}, handoff_to_dynamic=False)


def _sink() -> MagicMock:
    m = MagicMock()
    m.begin_episode = MagicMock()
    m.end_episode = MagicMock()
    return m


def _kernel_direct_answer() -> SimpleNamespace:
    async def _route(_t: str):
        return "DIRECT_ANSWER", "ok"

    return SimpleNamespace(
        active_sessions={},
        session_locks={},
        chat_locale_overrides={},
        bus=MagicMock(),
        memory=MagicMock(),
        router=MagicMock(),
        toolbox=MagicMock(),
        immunity=MagicMock(),
        episodic_memory=None,
        planner=None,
        intent_router=MagicMock(route_task=AsyncMock(side_effect=_route)),
        intent_template_registry=None,
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
        _get_current_persona=lambda: "s8",
    )


async def _session_lock_seq() -> None:
    kernel = SimpleNamespace(session_locks={}, active_sessions={})
    dp = DecisionProcessor(kernel)  # type: ignore[arg-type]
    for i in range(40):
        await dp._acquire_session_lock("chat-s8", f"trace-{i}")
        await dp._release_session_lock("chat-s8")
    assert not kernel.session_locks["chat-s8"].locked()


def test_session_lock_sequential_acquire_release_many_times() -> None:
    asyncio.run(_session_lock_seq())


async def _session_lock_second() -> None:
    kernel = SimpleNamespace(session_locks={}, active_sessions={})
    dp = DecisionProcessor(kernel)  # type: ignore[arg-type]
    await dp._acquire_session_lock("c", "t1")
    kernel._send_reply = AsyncMock()
    with pytest.raises(asyncio.CancelledError):
        await dp._acquire_session_lock("c", "t2")
    await dp._release_session_lock("c")


def test_session_lock_second_acquire_while_held_raises_cancelled() -> None:
    asyncio.run(_session_lock_second())


async def _sequential_process_direct(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(DecisionProcessor, "_append_stop_audit_daily", lambda *a, **k: None)
    monkeypatch.setattr(DecisionProcessor, "_write_session_export_log", lambda *a, **k: None)
    monkeypatch.setattr(
        "adami_kernel.cortex.decision_processor.get_experience_sink", lambda: _sink()
    )

    kernel = _kernel_direct_answer()
    dp = DecisionProcessor(kernel)  # type: ignore[arg-type]

    for i in range(15):
        ev = AdamiEvent(
            trace_id=f"s8-seq-{i}",
            source_module="user.prompt",
            target_topic="system.events",
            priority=EventPriority.HIGH,
            payload={"task": f"ping-{i}", "chat_id": "42"},
        )
        await dp.process(ev)

    lk = kernel.session_locks.get("42")
    assert lk is None or not lk.locked()


def test_sequential_process_direct_answer_no_lock_stack(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_sequential_process_direct(monkeypatch))


async def _concurrent_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(DecisionProcessor, "_append_stop_audit_daily", lambda *a, **k: None)
    monkeypatch.setattr(DecisionProcessor, "_write_session_export_log", lambda *a, **k: None)
    monkeypatch.setattr(
        "adami_kernel.cortex.decision_processor.get_experience_sink", lambda: _sink()
    )

    kernel = _kernel_direct_answer()
    dp = DecisionProcessor(kernel)  # type: ignore[arg-type]

    ev1 = AdamiEvent(
        trace_id="s8-p1",
        source_module="user.prompt",
        target_topic="system.events",
        priority=EventPriority.HIGH,
        payload={"task": "a", "chat_id": "99"},
    )
    ev2 = AdamiEvent(
        trace_id="s8-p2",
        source_module="user.prompt",
        target_topic="system.events",
        priority=EventPriority.HIGH,
        payload={"task": "b", "chat_id": "99"},
    )

    async def run1() -> None:
        await dp.process(ev1)

    async def run2() -> None:
        await asyncio.sleep(0.02)
        try:
            await dp.process(ev2)
        except asyncio.CancelledError:
            return

    await asyncio.wait_for(asyncio.gather(run1(), run2()), timeout=5.0)
    lock = kernel.session_locks.get("99")
    assert lock is None or not lock.locked()


def test_concurrent_process_same_chat_one_cancels_no_deadlock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asyncio.run(_concurrent_process(monkeypatch))


def test_action_family_template_blocked_without_ack_or_permission(
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

    execute_mock = AsyncMock(
        side_effect=AssertionError("ACTION template execute must not run without ack/permission")
    )

    class _GateHandler:
        async def match_score(self, classification):  # noqa: ANN001
            return 1.0 if classification.primary_type == "action.test" else 0.0

        async def execute(self, context):  # noqa: ANN001
            return await execute_mock()

    reg2 = TemplateRegistry(min_match_score=0.0)
    reg2.register("action.test", _GateHandler())

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
        intent_template_registry=reg2,
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
        _get_current_persona=lambda: "s8",
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
                "t-s8-action",
                router_tag="COMPLEX_TASK",
                router_data=None,
                trace_span=None,
            )

    handled, meta = asyncio.run(_run())
    assert handled is True
    assert meta is None
    assert not execute_mock.called
    kernel._send_reply.assert_awaited()
    reply_text = str(kernel._send_reply.await_args[0][1]).lower()
    assert "action-type" in reply_text or "action" in reply_text or "操作" in reply_text


def test_action_family_runs_with_router_ack(
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

    reg = TemplateRegistry(min_match_score=0.0)
    reg.register("action.test", _ActionHandler())

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
        _get_current_persona=lambda: "s8",
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
                "t-s8-ack",
                router_tag="COMPLEX_TASK",
                router_data={"intent_action_user_ack": True},
                trace_span=None,
            )

    handled, _meta = asyncio.run(_run())
    assert handled is True
    args = kernel._send_reply.await_args[0]
    assert "ACTION_BODY" in str(args[1])


def test_template_execute_timeout_sends_user_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED", True)
    monkeypatch.setattr(settings, "ADAMI_INTENT_CLASSIFIER_MIN_CONFIDENCE", 0.5)
    monkeypatch.setattr(settings, "ADAMI_INTENT_TEMPLATE_EXECUTE_TIMEOUT_SEC", 0.08)

    weather_cls = IntentClassificationResult(
        primary_family=IntentFamily.RETRIEVAL,
        primary_type=IntentType.RETRIEVAL_WEATHER,
        confidence=0.95,
        slots={},
        route="template",
        reason_codes=["rule"],
    )

    reg = TemplateRegistry(min_match_score=0.0)
    reg.register("retrieval.weather", _SlowHandler())

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
        _get_current_persona=lambda: "s8",
    )

    async def _run() -> tuple[bool, object]:
        dp = DecisionProcessor(kernel)  # type: ignore[arg-type]
        with (
            patch(
                "adami_kernel.cortex.intent_adaptive.rule_classifier.rule_classify_after_router",
                return_value=weather_cls,
            ),
            patch(
                "adami_kernel.cortex.intent_adaptive.llm_classifier.maybe_llm_classify_with_settings",
                new=AsyncMock(return_value=None),
            ),
        ):
            return await dp._maybe_route_intent_adaptive(
                "weather in London",
                "1",
                "cli",
                "t-s8-slow",
                router_tag="COMPLEX_TASK",
                router_data=None,
                trace_span=None,
            )

    handled, meta = asyncio.run(_run())
    assert handled is True
    assert meta is None
    text = str(kernel._send_reply.await_args[0][1])
    assert "timeout" in text.lower() or "超时" in text


def test_llm_phase_outer_timeout_falls_back_to_rule(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED", True)
    monkeypatch.setattr(settings, "ADAMI_INTENT_LLM_CLASSIFIER_ENABLED", True)
    monkeypatch.setattr(settings, "ADAMI_INTENT_ADAPTIVE_LLM_PHASE_TIMEOUT_SEC", 0.06)
    monkeypatch.setattr(settings, "ADAMI_INTENT_CLASSIFIER_MIN_CONFIDENCE", 0.99)

    rule_cls = IntentClassificationResult(
        primary_family=IntentFamily.RETRIEVAL,
        primary_type=IntentType.RETRIEVAL_WEATHER,
        confidence=0.6,
        slots={},
        route="dynamic",
        reason_codes=["rule"],
    )

    async def _hang(*_a, **_k):
        await asyncio.sleep(1.0)
        return None

    reg = TemplateRegistry(min_match_score=0.0)

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
        planner=MagicMock(plan_and_execute=AsyncMock(return_value="PLAN_OK")),
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
        _get_current_persona=lambda: "s8",
    )

    async def _run() -> tuple[bool, object]:
        dp = DecisionProcessor(kernel)  # type: ignore[arg-type]
        with (
            patch(
                "adami_kernel.cortex.intent_adaptive.rule_classifier.rule_classify_after_router",
                return_value=rule_cls,
            ),
            patch(
                "adami_kernel.cortex.intent_adaptive.llm_classifier.maybe_llm_classify_with_settings",
                new=_hang,
            ),
        ):
            return await dp._maybe_route_intent_adaptive(
                "weather in London",
                "1",
                "cli",
                "t-s8-llm",
                router_tag="COMPLEX_TASK",
                router_data=None,
                trace_span=None,
            )

    handled, meta = asyncio.run(_run())
    assert handled is False
    assert meta is not None
    assert meta.get("route") == "dynamic"
