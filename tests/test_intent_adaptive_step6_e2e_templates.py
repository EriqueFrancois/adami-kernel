# tests/test_intent_adaptive_step6_e2e_templates.py
"""Step 6 E2E: classification → built-in template → plain text reply."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from adami_kernel.config import settings
from adami_kernel.cortex.decision_processor import DecisionProcessor
from adami_kernel.cortex.intent_adaptive.bootstrap_templates import (
    register_builtin_intent_templates,
)
from adami_kernel.cortex.intent_adaptive.models import IntentType
from adami_kernel.cortex.intent_adaptive.template_registry import (
    NoOpTemplateHandler,
    TemplateRegistry,
)


def _registry_with_builtins() -> TemplateRegistry:
    reg = TemplateRegistry(min_match_score=0.0)
    reg.register(IntentType.UNKNOWN, NoOpTemplateHandler())
    register_builtin_intent_templates(reg)
    return reg


def _kernel(reg: TemplateRegistry, *, web_hits: list | None) -> SimpleNamespace:
    planner = MagicMock()
    planner.plan_and_execute = AsyncMock(return_value="PLANNER_SHOULD_NOT_RUN")

    async def _search(*_a, **_k):
        return web_hits if web_hits is not None else []

    web = SimpleNamespace(search=_search)
    toolbox = SimpleNamespace(web=web)

    return SimpleNamespace(
        active_sessions={},
        session_locks={},
        chat_locale_overrides={},
        bus=MagicMock(),
        memory=MagicMock(),
        router=MagicMock(
            call_llm=AsyncMock(
                side_effect=AssertionError("call_llm unexpected when web hits present")
            )
        ),
        toolbox=toolbox,
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
        _get_current_persona=lambda: "e2e6",
    )


@pytest.mark.parametrize(
    ("task", "needles"),
    [
        ("今天北京气温怎么样", ("天气", "Weather")),
        ("What is the BTC price today", ("加密货币速览", "Crypto snapshot")),
        ("请查询现在比特币的价格", ("加密货币速览", "Crypto snapshot")),
    ],
)
def test_e2e_template_reply_has_fixed_markers(
    monkeypatch: pytest.MonkeyPatch, task: str, needles: tuple[str, ...]
) -> None:
    monkeypatch.setattr(settings, "ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED", True)
    # Force API path to miss so this E2E asserts the web-search fallback shape.
    import adami_kernel.cortex.intent_adaptive.templates.retrieval_crypto as _crypto_mod
    import adami_kernel.cortex.intent_adaptive.templates.retrieval_weather as _weather_mod

    async def _api_none(*_a, **_k):  # noqa: ANN001
        return None

    monkeypatch.setattr(_crypto_mod, "_fetch_coingecko_simple_price", _api_none)
    monkeypatch.setattr(_weather_mod, "_fetch_open_meteo_city_latlon", _api_none)
    reg = _registry_with_builtins()
    # Include weather/price tokens so template-side filtering keeps the row.
    hits = [
        {
            "title": "Demo hit",
            "href": "https://example.test",
            "body": "Synthetic weather / price snippet for test. 北京 天气 BTC price",
        }
    ]
    kernel = _kernel(reg, web_hits=hits)

    async def _run() -> None:
        dp = DecisionProcessor(kernel)  # type: ignore[arg-type]
        await dp._dispatch_complex_task(
            task,
            "cli",
            "cli",
            "trace-e2e-step6",
            router_data=None,
            trace_span=None,
        )

    asyncio.run(_run())

    kernel.planner.plan_and_execute.assert_not_called()
    assert kernel._send_reply.await_count >= 1
    text = str(kernel._send_reply.await_args[0][1])
    assert any(n in text for n in needles)
    assert "<!-- intent-template:" not in text
    # Depending on template-side filters, the synthetic hit may be dropped and the stub path may be used.


def test_e2e_stub_path_when_web_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED", True)
    reg = _registry_with_builtins()
    kernel = _kernel(reg, web_hits=[])

    async def _run() -> None:
        dp = DecisionProcessor(kernel)  # type: ignore[arg-type]
        await dp._dispatch_complex_task(
            "weather in London please",
            "cli",
            "cli",
            "trace-e2e-stub",
            router_data=None,
            trace_span=None,
        )

    asyncio.run(_run())
    kernel.planner.plan_and_execute.assert_not_called()
    text = str(kernel._send_reply.await_args[0][1])
    assert "天气" in text or "Weather" in text
    assert "<!-- intent-template:" not in text
