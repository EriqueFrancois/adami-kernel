# tests/test_intent_adaptive_step6_acceptance.py
"""
Step 6 acceptance tests (see ``docs/intent_adaptive_pipeline.md`` § Step 6 — Acceptance test plan).

E2E Markdown / stub paths: ``tests/test_intent_adaptive_step6_e2e_templates.py``.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from adami_kernel.cortex.intent_adaptive.bootstrap_templates import (
    register_builtin_intent_templates,
)
from adami_kernel.cortex.intent_adaptive.models import (
    IntentClassificationResult,
    IntentFamily,
    IntentType,
)
from adami_kernel.cortex.intent_adaptive.template_registry import (
    NoOpTemplateHandler,
    TemplateExecutionContext,
    TemplateRegistry,
)
from adami_kernel.cortex.intent_adaptive.templates._web_snippets import plain_lines_from_search_hits
from adami_kernel.i18n.catalog import default_translator

_REPO = Path(__file__).resolve().parents[1]
_README = _REPO / "README.md"
_LOCALES = _REPO / "src" / "adami_kernel" / "i18n" / "locales"


def _disable_weather_public_api(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prevent external network calls in CI/unit tests."""
    from adami_kernel.cortex.intent_adaptive.templates import retrieval_weather as weather_mod

    async def _no_public_api(*_a, **_k):  # noqa: ANN001
        return ""

    monkeypatch.setattr(weather_mod, "_try_weather_from_public_api", _no_public_api)


def _registry_with_builtins() -> TemplateRegistry:
    reg = TemplateRegistry(min_match_score=0.0)
    reg.register(IntentType.UNKNOWN, NoOpTemplateHandler())
    register_builtin_intent_templates(reg)
    return reg


# --- S6-A. Registration ---


def test_s6a1_bootstrap_registers_weather_and_crypto() -> None:
    reg = _registry_with_builtins()
    types = [pair[0] for pair in reg.registered_pairs()]
    assert IntentType.RETRIEVAL_WEATHER in types
    assert IntentType.RETRIEVAL_CRYPTO in types


# --- S6-D. Snippet helper ---


def test_s6d1_plain_lines_from_search_hits() -> None:
    s = plain_lines_from_search_hits(
        [
            {"title": "A\x00\u200b", "body": "al\x0cpha   \n"},
            {"title": "", "body": "beta"},
        ]
    )
    assert "A" in s and "alpha" in s and "beta" in s
    assert "\x00" not in s and "\u200b" not in s


def test_s6d1b_snippet_strips_common_boilerplate() -> None:
    s = plain_lines_from_search_hits(
        [
            {
                "title": "天气网",
                "body": "北京阴云... 客服电话：010-68409444 京公网安备11041400134号 京ICP证010385-2号",
            }
        ],
        max_items=1,
        body_max=200,
    )
    assert "ICP" not in s and "公网安备" not in s and "客服电话" not in s


# --- S6-E. README ---


def test_s6e1_readme_lists_builtin_intent_types_and_step6() -> None:
    text = _README.read_text(encoding="utf-8")
    assert "retrieval.weather" in text
    assert "retrieval.crypto" in text
    assert "doc.intent_adaptive.step6_templates" in text
    assert "register_builtin_intent_templates" in text or "bootstrap_templates" in text


# --- S6-F. i18n catalog ---


@pytest.mark.parametrize("locale", ["en", "zh-Hans"])
@pytest.mark.parametrize(
    "key",
    [
        "doc.intent_adaptive.step6_templates",
        "intent.help.body",
        "intent.help.supported_types",
        "intent.template.weather_title",
        "intent.template.weather_stub",
        "intent.template.crypto_title",
        "intent.template.crypto_stub",
    ],
)
def test_s6f1_catalog_keys_non_empty(locale: str, key: str) -> None:
    path = _LOCALES / locale / "common.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert key in data and str(data[key]).strip()


def test_s6f2_bilingual_help_and_step6_doc_differ() -> None:
    tr = default_translator()
    for key in ("intent.help.body", "doc.intent_adaptive.step6_templates"):
        assert tr.t(key, locale="en") != tr.t(key, locale="zh-Hans"), key


def test_s6_api_prefers_public_api_over_web(monkeypatch: pytest.MonkeyPatch) -> None:
    from adami_kernel.cortex.intent_adaptive.templates import retrieval_crypto as crypto_mod
    from adami_kernel.cortex.intent_adaptive.templates import retrieval_weather as weather_mod
    from adami_kernel.cortex.intent_adaptive.templates.retrieval_crypto import (
        RetrievalCryptoTemplateHandler,
    )
    from adami_kernel.cortex.intent_adaptive.templates.retrieval_weather import (
        RetrievalWeatherTemplateHandler,
    )

    async def _cg(**_k):  # noqa: ANN001
        return {"usd": 70884.2, "cny": 510000.0}

    async def _geo(_name: str):  # noqa: ANN001
        return (39.9042, 116.4074, "Beijing")

    async def _cur(_lat: float, _lon: float):  # noqa: ANN001
        return {"temperature_2m": 18.3, "wind_speed_10m": 5.0, "wind_direction_10m": 225}

    monkeypatch.setattr(crypto_mod, "_fetch_coingecko_simple_price", _cg)
    monkeypatch.setattr(weather_mod, "_fetch_open_meteo_city_latlon", _geo)
    monkeypatch.setattr(weather_mod, "_fetch_open_meteo_current", _cur)

    # Web search should not be needed when API returns.
    async def _boom(*_a, **_k):  # noqa: ANN001
        raise AssertionError("web_search should not run when API succeeds")

    async def _run() -> None:
        cctx = TemplateExecutionContext(
            task_text="请查询现在比特币的价格",
            chat_id="1",
            platform="cli",
            trace_id="s6-api-crypto",
            classification=None,
            web_search=_boom,
            router_call_llm=None,
        )
        out = await RetrievalCryptoTemplateHandler().execute(cctx)
        assert "BTC (USD)" in out.reply_markdown
        assert "CoinGecko" in out.reply_markdown

        wctx = TemplateExecutionContext(
            task_text="帮我查询北京市今天的天气",
            chat_id="1",
            platform="cli",
            trace_id="s6-api-weather",
            classification=None,
            web_search=_boom,
            router_call_llm=None,
        )
        out2 = await RetrievalWeatherTemplateHandler().execute(wctx)
        assert "Open-Meteo" in out2.reply_markdown
        assert "实况" in out2.reply_markdown

    asyncio.run(_run())


def test_s6_weather_filters_city_mismatch_noise(monkeypatch: pytest.MonkeyPatch) -> None:
    from adami_kernel.cortex.intent_adaptive.templates.retrieval_weather import (
        RetrievalWeatherTemplateHandler,
    )
    _disable_weather_public_api(monkeypatch)

    async def _search(*_a, **_k):  # noqa: ANN001
        return [
            {
                "title": "天气 - 广州市 - 14天预报",
                "href": "https://ventusky.com/guangzhou",
                "body": "广州市 - 14天的气象预报",
            },
            {
                "title": "国内天气预报",
                "href": "https://weather.com.cn/weather1d/101010100.shtml",
                "body": "北京18.3℃ 西南风 微风",
            },
        ]

    async def _run() -> None:
        ctx = TemplateExecutionContext(
            task_text="帮我查询北京市今天的天气",
            chat_id="1",
            platform="cli",
            trace_id="s6-weather-filter",
            classification=None,
            web_search=_search,
            router_call_llm=None,
        )
        out = await RetrievalWeatherTemplateHandler().execute(ctx)
        text = out.reply_markdown
        assert "广州" not in text
        assert "北京" in text

    asyncio.run(_run())


def test_s6_weather_filters_windy_app_noise(monkeypatch: pytest.MonkeyPatch) -> None:
    from adami_kernel.cortex.intent_adaptive.templates.retrieval_weather import (
        RetrievalWeatherTemplateHandler,
    )
    _disable_weather_public_api(monkeypatch)

    async def _search(*_a, **_k):  # noqa: ANN001
        return [
            {
                "title": "成都市区, Chengdu Shi 风、浪和天气预报 — Windy.app",
                "href": "https://windy.app/forecast",
                "body": "成都市区 Chengdu Shi天气预报及实时风图风况...",
            },
            {
                "title": "成都天气预报10天",
                "href": "https://weather.com.cn/weather/101270101.shtml",
                "body": "成都 今日 18℃",
            },
        ]

    async def _run() -> None:
        ctx = TemplateExecutionContext(
            task_text="帮我查询成都市今天的天气",
            chat_id="1",
            platform="cli",
            trace_id="s6-weather-windy-filter",
            classification=None,
            web_search=_search,
            router_call_llm=None,
        )
        out = await RetrievalWeatherTemplateHandler().execute(ctx)
        assert "windy.app" not in out.reply_markdown.lower()
        assert "成都" in out.reply_markdown

    asyncio.run(_run())


def test_s6_weather_filters_wrong_province_from_trusted_portal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: asking Lanzhou must not return Henan portal pages."""
    from adami_kernel.cortex.intent_adaptive.templates.retrieval_weather import (
        RetrievalWeatherTemplateHandler,
    )
    _disable_weather_public_api(monkeypatch)

    async def _search(*_a, **_k):  # noqa: ANN001
        return [
            {
                "title": "河南首页 - 河南",
                "href": "https://nmc.cn/publish/forecast/HA.html",
                "body": "最高气温：北中部...",
            },
            {
                "title": "兰州天气",
                "href": "https://weather.com.cn/weather1d/101160101.shtml",
                "body": "兰州 20℃",
            },
        ]

    async def _run() -> None:
        ctx = TemplateExecutionContext(
            task_text="帮我查询兰州市今天的天气",
            chat_id="1",
            platform="cli",
            trace_id="s6-weather-lanzhou-filter",
            classification=None,
            web_search=_search,
            router_call_llm=None,
        )
        out = await RetrievalWeatherTemplateHandler().execute(ctx)
        text = out.reply_markdown
        assert "河南" not in text
        assert "兰州" in text

    asyncio.run(_run())


# --- S6-H. Registry resolve + execute (no DecisionProcessor) ---


def test_s6h1_resolve_weather_handler_executes_with_marker(monkeypatch: pytest.MonkeyPatch) -> None:
    _disable_weather_public_api(monkeypatch)
    async def _run() -> None:
        reg = _registry_with_builtins()
        c = IntentClassificationResult(
            primary_family=IntentFamily.RETRIEVAL,
            primary_type=IntentType.RETRIEVAL_WEATHER,
            confidence=0.99,
            slots={"query_excerpt": "Paris rain"},
            route="dynamic",
        )
        h = await reg.resolve(c)
        assert h is not None
        ctx = TemplateExecutionContext(
            task_text="weather in Paris",
            chat_id="1",
            platform="cli",
            trace_id="s6h1",
            classification=c,
            web_search=lambda *_a, **_k: [],  # noqa: ANN001
        )
        out = await h.execute(ctx)
        assert "<!-- intent-template:" not in out.reply_markdown
        assert "Weather" in out.reply_markdown or "天气" in out.reply_markdown
        assert out.handoff_to_dynamic is False

    asyncio.run(_run())
