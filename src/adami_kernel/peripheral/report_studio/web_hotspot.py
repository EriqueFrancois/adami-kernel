"""DDG-based web hotspots (X downgrade): fixed English queries, blacklist, dedupe vs RSS."""

from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import urlparse

from adami_kernel.config import settings
from adami_kernel.peripheral.report_studio.rss_aggregate import (
    _canonical_link,
    _title_similarity,
)

logger = logging.getLogger("AdamI-ReportStudio-WebHotspot")

SearchFn = Callable[..., Any]


def _host_blocked(href: str, blacklist: List[str]) -> bool:
    if not href:
        return True
    host = (urlparse(href).netloc or "").lower()
    for frag in blacklist:
        f = (frag or "").lower().strip()
        if f and f in host:
            return True
    return False


def _dedupe_against_rss(
    rows: List[Dict[str, str]],
    *,
    rss_items: List[Dict[str, Any]],
    blacklist: List[str],
) -> List[Dict[str, Any]]:
    rss_links = {_canonical_link(str(x.get("link") or "")) for x in rss_items}
    rss_titles = [str(x.get("title") or "") for x in rss_items]
    out: List[Dict[str, Any]] = []
    seen_href: set[str] = set()
    for r in rows:
        href = (r.get("href") or "").strip()
        title = (r.get("title") or "").strip()
        body = (r.get("body") or "").strip()
        if not title and not href:
            continue
        if _host_blocked(href, blacklist):
            continue
        ch = _canonical_link(href)
        if ch and ch in rss_links:
            continue
        if href and href in seen_href:
            continue
        if href:
            seen_href.add(href)
        dup_title = False
        for rt in rss_titles:
            if rt and _title_similarity(title, rt) >= 0.78:
                dup_title = True
                break
        if dup_title:
            continue
        out.append(
            {
                "title": title[:240] or "Web hit",
                "summary": (body or title)[:500],
                "link": href or None,
            }
        )
    return out


async def world_web_hotspot_provider(
    search_fn: Optional[SearchFn],
    *,
    queries: List[str],
    rss_items: List[Dict[str, Any]],
    blacklist: List[str],
    top_n: int,
) -> List[Dict[str, Any]]:
    if int(top_n) <= 0:
        return []
    if bool(getattr(settings, "ADAMI_SIM_OFFLINE", False)):
        return []
    if search_fn is None or not queries:
        return []
    merged: List[Dict[str, str]] = []
    for q in queries:
        q2 = (q or "").strip()
        if not q2:
            continue
        try:
            chunk = await search_fn(q2, max(5, top_n))
            if isinstance(chunk, list):
                merged.extend([x for x in chunk if isinstance(x, dict)])
        except Exception as e:
            logger.warning("[ReportStudio] web hotspot search failed q=%r err=%s", q2, e)
    return _dedupe_against_rss(merged, rss_items=rss_items, blacklist=blacklist)[:top_n]
