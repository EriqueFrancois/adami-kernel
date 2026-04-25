# tests/test_intent_adaptive_step5_acceptance.py
"""
Step 5 acceptance tests (see ``docs/intent_adaptive_pipeline.md`` § Step 5 — Acceptance test plan).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from adami_kernel.config import settings
from adami_kernel.cortex.decision_processor import DecisionProcessor
from adami_kernel.cortex.intent_adaptive.outcomes import TemplateOutcome
from adami_kernel.cortex.intent_adaptive.template_registry import TemplateRegistry
from adami_kernel.i18n.catalog import default_translator

_REPO = Path(__file__).resolve().parents[1]
_README = _REPO / "README.md"
_LOCALES = _REPO / "src" / "adami_kernel" / "i18n" / "locales"


def test_s5a_pipeline_and_fallback_defaults() -> None:
    assert settings.ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED is False
    assert settings.ADAMI_INTENT_ADAPTIVE_FALLBACK_NOTICE is False


def test_s5b1_decision_processor_has_intent_adaptive_hook() -> None:
    assert callable(getattr(DecisionProcessor, "_maybe_route_intent_adaptive", None))


def test_s5b2_pipeline_off_returns_false_without_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED", False)
    planner = MagicMock()
    planner.plan_and_execute = AsyncMock(return_value="SHOULD_NOT_RUN")
    kernel = MagicMock()
    kernel.skill_router = None
    kernel.episodic_memory = None
    kernel.planner = planner
    kernel.intent_template_registry = MagicMock()

    async def _run() -> bool:
        dp = DecisionProcessor(kernel)  # type: ignore[arg-type]
        return await dp._maybe_route_intent_adaptive(
            "hello",
            "1",
            "cli",
            "t-s5b2",
            router_tag="COMPLEX_TASK",
            router_data=None,
        )

    assert asyncio.run(_run()) == (False, None)
    planner.plan_and_execute.assert_not_called()


def test_s5c_component_initializer_registry() -> None:
    try:
        import aiosqlite  # noqa: F401
    except ModuleNotFoundError:
        pytest.skip("aiosqlite missing: cannot import ComponentInitializer in this env")

    from adami_kernel.core.component_initializer import ComponentInitializer

    comps = ComponentInitializer().initialize_components(kernel=None)
    reg = comps.get("intent_template_registry")
    assert reg is not None
    assert isinstance(reg, TemplateRegistry)


class _WeatherStub:
    async def match_score(self, classification):  # noqa: ANN001
        return 1.0 if classification.primary_type == "retrieval.weather" else 0.0

    async def execute(self, context):  # noqa: ANN001
        _ = context
        return TemplateOutcome(
            reply_markdown="S5_ACCEPT_WEATHER",
            telemetry={},
            handoff_to_dynamic=False,
        )


def _kernel_for_s5d(registry: TemplateRegistry) -> SimpleNamespace:
    planner = MagicMock()
    planner.plan_and_execute = AsyncMock(return_value="PLAN_OK")
    router = MagicMock()
    router.call_llm = AsyncMock(
        side_effect=AssertionError("LLM must not run for strong rule tier in S5-D1")
    )
    send = AsyncMock()
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
        _get_current_persona=lambda: "s5",
    )


def test_s5d1_template_skips_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    reg = TemplateRegistry(min_match_score=0.0)
    reg.register("retrieval.weather", _WeatherStub())
    kernel = _kernel_for_s5d(reg)
    monkeypatch.setattr(settings, "ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED", True)

    async def _run() -> None:
        dp = DecisionProcessor(kernel)  # type: ignore[arg-type]
        await dp._dispatch_complex_task(
            "What is the weather in Paris tomorrow?",
            "1",
            "telegram",
            "t-s5d1",
            router_data=None,
        )

    asyncio.run(_run())
    kernel.planner.plan_and_execute.assert_not_called()
    assert kernel._send_reply.await_count >= 1
    bodies = [str(c[0][1]) for c in kernel._send_reply.await_args_list]
    assert any("S5_ACCEPT_WEATHER" in b for b in bodies)


def test_s5d2_no_rule_hit_reaches_planner(monkeypatch: pytest.MonkeyPatch) -> None:
    reg = TemplateRegistry(min_match_score=0.0)
    reg.register("retrieval.weather", _WeatherStub())
    kernel = _kernel_for_s5d(reg)
    monkeypatch.setattr(settings, "ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED", True)
    kernel.router.call_llm = AsyncMock(return_value="{}")

    async def _run() -> None:
        dp = DecisionProcessor(kernel)  # type: ignore[arg-type]
        await dp._dispatch_complex_task(
            "zzzz_unique_no_rule_hit_aaaa",
            "1",
            "telegram",
            "t-s5d2",
            router_data=None,
        )

    asyncio.run(_run())
    kernel.planner.plan_and_execute.assert_awaited_once()


@pytest.mark.parametrize("locale", ["en", "zh-Hans"])
@pytest.mark.parametrize(
    "key",
    ["doc.intent_adaptive.step5_decision_wiring", "intent.adaptive.user.fallback_to_planner"],
)
def test_s5e_catalog_non_empty(locale: str, key: str) -> None:
    path = _LOCALES / locale / "common.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert key in data and str(data[key]).strip()


def test_s5e_doc_and_user_strings_differ_by_locale() -> None:
    tr = default_translator()
    for key in (
        "doc.intent_adaptive.step5_decision_wiring",
        "intent.adaptive.user.fallback_to_planner",
    ):
        a = tr.t(key, locale="en")
        b = tr.t(key, locale="zh-Hans")
        assert a != b, key


def test_s5f_readme_mentions_step5_signals() -> None:
    text = _README.read_text(encoding="utf-8")
    assert "ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED" in text
    assert "doc.intent_adaptive.step5_decision_wiring" in text
    assert "doc.intent_adaptive.step51_observability" in text
    assert "[intent_adaptive]" in text
