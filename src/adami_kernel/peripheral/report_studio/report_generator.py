from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from adami_kernel.config import settings
from adami_kernel.hippocampus.second_brain import SecondBrainManager
from adami_kernel.i18n.locale_utils import normalize_locale, pick_first_supported
from adami_kernel.i18n.request_locale import get_request_locale
from adami_kernel.peripheral.report_studio.curated_report_providers import (
    ai_progress_curated_provider,
    market_moves_curated_provider,
    world_news_curated_provider,
)
from adami_kernel.peripheral.report_studio.report_config import ReportType
from adami_kernel.peripheral.report_studio.report_providers import (
    SearchFn,
    crypto_spot_prices_provider,
    system_updates_provider,
)
from adami_kernel.peripheral.report_studio.report_renderer import (
    RenderedReport,
    ReportRenderer,
    localized_report_title,
)


@dataclass
class GeneratedReport:
    rendered: RenderedReport
    data: Dict[str, Any]


def _utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


async def _translate_news_items(
    items: list[Dict[str, Any]],
    *,
    target_locale: str,
    call_llm: Callable[[str], Awaitable[str]],
    max_items: int,
) -> None:
    from adami_kernel.i18n.external_text import translate_external_summary_for_ui

    for it in items[:max_items]:
        blob = f"{(it.get('title') or '').strip()}\n{(it.get('summary') or '').strip()}".strip()
        if len(blob) < 6:
            continue
        out = await translate_external_summary_for_ui(
            blob, target_locale=target_locale, call_llm=call_llm
        )
        lines = out.strip().split("\n", 1)
        it["title"] = (lines[0] or it.get("title") or "").strip()[:240]
        it["summary"] = ((lines[1] if len(lines) > 1 else "") or it.get("summary") or "").strip()[
            :400
        ]


async def generate_fixed_blocks_report(
    *,
    report_type: ReportType,
    title: Optional[str] = None,
    timezone_name: str,
    period_start: datetime,
    period_end: datetime,
    top_n_system: int = 3,
    top_n_news: int = 5,
    top_n_ai: int = 5,
    top_n_market: int = 5,
    second_brain: Optional[SecondBrainManager] = None,
    search_fn: Optional[SearchFn] = None,
    locale: Optional[str] = None,
    translate_call_llm: Optional[Callable[[str], Awaitable[str]]] = None,
) -> GeneratedReport:
    sb = second_brain or SecondBrainManager()
    renderer = ReportRenderer(sb)
    supported = tuple(settings.ADAMI_SUPPORTED_LOCALES)
    loc = normalize_locale(locale or get_request_locale() or settings.effective_report_locale())
    loc = pick_first_supported(loc, supported=supported, hard_fallback="en")
    doc_title = title if title is not None else localized_report_title(report_type, loc)

    period_start_utc = _as_utc(period_start)
    period_end_utc = _as_utc(period_end)

    kernel_log_path = getattr(settings, "path_kernel_log_file", ".adami_data/kernel.log")

    system_updates = await system_updates_provider(
        kernel_log_path=kernel_log_path, top_n=top_n_system, locale=loc
    )

    world_news = await world_news_curated_provider(
        search_fn,
        period_start=period_start_utc,
        period_end=period_end_utc,
        top_n_rss=top_n_news,
        top_n_web=top_n_news,
    )
    ai_progress = await ai_progress_curated_provider(
        report_type=report_type,
        period_start=period_start_utc,
        period_end=period_end_utc,
        top_n_github=top_n_ai,
        top_n_media=top_n_ai,
    )
    market_moves = await market_moves_curated_provider(
        period_start=period_start_utc,
        period_end=period_end_utc,
        top_n=top_n_market,
    )

    if bool(getattr(settings, "ADAMI_REPORT_CRYPTO_ENABLED", True)):
        crypto = await crypto_spot_prices_provider(
            timeout_sec=float(getattr(settings, "ADAMI_REPORT_CRYPTO_TIMEOUT_SEC", 12.0)),
            locale=loc,
        )
    else:
        crypto = {"items": [], "sources": [], "error": None, "error_user": None}

    data: Dict[str, Any] = {
        "system_updates": {"top_n": top_n_system, **system_updates},
        "world_news": {"top_n": top_n_news, **world_news},
        "ai_progress": {"top_n": top_n_ai, **ai_progress},
        "market_moves": {"top_n": top_n_market, **market_moves},
        "crypto_spot": crypto,
    }

    if (
        bool(getattr(settings, "ADAMI_REPORT_TRANSLATE_NEWS", True))
        and translate_call_llm is not None
    ):
        max_it = int(getattr(settings, "ADAMI_REPORT_TRANSLATE_MAX_ITEMS", 6))
        await _translate_news_items(
            data["world_news"]["items"],
            target_locale=loc,
            call_llm=translate_call_llm,
            max_items=max_it,
        )
        await _translate_news_items(
            data["world_news"].get("web_hotspot_items") or [],
            target_locale=loc,
            call_llm=translate_call_llm,
            max_items=max_it,
        )
        await _translate_news_items(
            data["ai_progress"].get("github_items") or [],
            target_locale=loc,
            call_llm=translate_call_llm,
            max_items=max_it,
        )
        await _translate_news_items(
            data["ai_progress"].get("media_items") or [],
            target_locale=loc,
            call_llm=translate_call_llm,
            max_items=max_it,
        )
        await _translate_news_items(
            data["market_moves"]["items"],
            target_locale=loc,
            call_llm=translate_call_llm,
            max_items=max_it,
        )

    rendered = renderer.render(
        report_type=report_type,
        title=doc_title,
        period_start=_utc_iso(period_start_utc),
        period_end=_utc_iso(period_end_utc),
        timezone=timezone_name,
        data=data,
        locale=loc,
        supported_locales=supported,
    )
    return GeneratedReport(rendered=rendered, data=data)
