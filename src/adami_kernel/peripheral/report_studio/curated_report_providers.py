"""Curated RSS + GitHub + DDG hotspot providers for Report Studio (replaces last30days for three blocks)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional

from adami_kernel.peripheral.report_studio.github_ai_repos import github_ai_repo_items_for_report
from adami_kernel.peripheral.report_studio.report_config import ReportType
from adami_kernel.peripheral.report_studio.report_providers import SearchFn
from adami_kernel.peripheral.report_studio.rss_aggregate import aggregate_whitelist_rss
from adami_kernel.peripheral.report_studio.rss_config import load_report_feed_config
from adami_kernel.peripheral.report_studio.web_hotspot import world_web_hotspot_provider


async def world_news_curated_provider(
    search_fn: Optional[SearchFn],
    *,
    period_start: datetime,
    period_end: datetime,
    top_n_rss: int,
    top_n_web: int,
) -> Dict[str, Any]:
    cfg = load_report_feed_config()
    feeds = cfg.get("world_media") or []
    items, sources = await aggregate_whitelist_rss(
        feeds,
        period_start=period_start,
        period_end=period_end,
        top_n=top_n_rss,
    )
    web_items = await world_web_hotspot_provider(
        search_fn,
        queries=list(cfg.get("world_web_hotspot_queries") or []),
        rss_items=items,
        blacklist=list(cfg.get("ddg_domain_blacklist_substrings") or []),
        top_n=top_n_web,
    )
    src = list(sources)
    src.append(
        {
            "backend": "ddg_hotspot",
            "queries": list(cfg.get("world_web_hotspot_queries") or []),
        }
    )
    return {
        "top_n": top_n_rss,
        "items": items,
        "web_hotspot_items": web_items,
        "sources": src,
        "cache_hit": False,
        "error": None,
    }


async def ai_progress_curated_provider(
    *,
    report_type: ReportType,
    period_start: datetime,
    period_end: datetime,
    top_n_github: int,
    top_n_media: int,
) -> Dict[str, Any]:
    cfg = load_report_feed_config()
    q = str(cfg.get("github_repo_search_query") or cfg.get("github_ai_search_query") or "").strip()
    per_page = int(
        cfg.get("github_repo_search_per_page") or cfg.get("github_ai_search_per_page") or 40
    )
    gh_items, _gh_note, _gh_err = await github_ai_repo_items_for_report(
        report_type=report_type,
        period_start=period_start,
        period_end=period_end,
        top_n=top_n_github,
        search_query=q or "is:public archived:false fork:false stars:>500",
        per_page=per_page,
    )
    media, sources = await aggregate_whitelist_rss(
        cfg.get("ai_media") or [],
        period_start=period_start,
        period_end=period_end,
        top_n=top_n_media,
    )
    src = [{"backend": "github_search", "query": q}] + list(sources)
    return {
        "top_n": max(top_n_github, top_n_media),
        "github_items": gh_items,
        "media_items": media,
        "sources": src,
        "cache_hit": False,
        "error": None,
    }


async def market_moves_curated_provider(
    *,
    period_start: datetime,
    period_end: datetime,
    top_n: int,
) -> Dict[str, Any]:
    cfg = load_report_feed_config()
    items, sources = await aggregate_whitelist_rss(
        cfg.get("finance") or [],
        period_start=period_start,
        period_end=period_end,
        top_n=top_n,
    )
    return {
        "top_n": top_n,
        "items": items,
        "sources": sources,
        "cache_hit": False,
        "error": None,
    }
