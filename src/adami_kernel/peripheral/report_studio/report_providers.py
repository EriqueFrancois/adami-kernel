from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

from adami_kernel.config import settings
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.catalog import default_translator
from adami_kernel.i18n.locale_utils import normalize_locale
from adami_kernel.integration.last30days_bridge import run_last30days

SearchFn = Callable[[str, int], Awaitable[List[Dict[str, str]]]]


def _rpt_kernel_signal_words(*, locale: Optional[str] = None) -> Dict[str, str]:
    loc = normalize_locale(locale or settings.effective_ui_default_locale())
    raw = i18n_t("rpt.kernel_signals_json", locale=loc)
    return json.loads(raw)


@dataclass
class ProviderItem:
    title: str
    summary: str
    link: Optional[str] = None


def _utc_z(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _build_last30days_topic(
    topic_core: str, *, period_start: datetime, period_end: datetime
) -> str:
    """last30days 子进程首参：单行 UTC 闭区间元数据接在主题后，避免输出首条被截断时丢失可读主题。"""
    ps, pe = _utc_z(period_start), _utc_z(period_end)
    core = (topic_core or "").strip()
    return f"{core} | UTC_WINDOW_INCLUSIVE {ps}..{pe} OUTSIDE_OMIT"


def _filter_stub_search_results(
    rows: List[Dict[str, str]], *, locale: Optional[str] = None
) -> List[Dict[str, str]]:
    """去掉 WebTool 在失败时返回的占位「假一条结果」。"""
    loc = normalize_locale(locale or settings.effective_ui_default_locale())
    bad = {
        i18n_t("webt.err.backend_title", locale=loc),
        i18n_t("webt.err.fail_title", locale=loc),
        i18n_t("webt.err.backend_title", locale="en"),
        i18n_t("webt.err.fail_title", locale="en"),
    }
    out: List[Dict[str, str]] = []
    for r in rows:
        title = (r.get("title") or "").strip()
        if title in bad:
            continue
        out.append(r)
    return out


_ISO_DATE_RE = re.compile(r"\b(20[2-3]\d)[-/](\d{1,2})[-/](\d{1,2})\b")


def _dates_in_text(text: str) -> List[date]:
    out: List[date] = []
    for m in _ISO_DATE_RE.finditer(text or ""):
        try:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            out.append(date(y, mo, d))
        except ValueError:
            continue
    return out


def filter_items_by_explicit_calendar_dates(
    items: List[ProviderItem],
    *,
    period_start: datetime,
    period_end: datetime,
) -> List[ProviderItem]:
    """若条目中能解析出 ``YYYY-MM-DD`` / ``YYYY/MM/DD``，任一落在报告 UTC 窗外则丢弃（收紧陈旧新闻）。"""
    ps = period_start.astimezone(timezone.utc).date()
    pe = period_end.astimezone(timezone.utc).date()
    kept: List[ProviderItem] = []
    for it in items:
        blob = f"{it.title} {it.summary}"
        ds = _dates_in_text(blob)
        if not ds:
            kept.append(it)
            continue
        if any((d < ps or d > pe) for d in ds):
            continue
        kept.append(it)
    return kept


def _clip(s: str, n: int = 240) -> str:
    t = (s or "").strip()
    if len(t) <= n:
        return t
    return t[: n - 1] + "…"


def _top_lines_from_kernel_log(
    log_path: str, *, top_n: int, locale: Optional[str] = None
) -> List[ProviderItem]:
    p = Path(log_path)
    if not p.is_file():
        return [ProviderItem(title="kernel.log missing", summary=f"not found: {log_path}")]
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return [ProviderItem(title="kernel.log unreadable", summary=str(e))]
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    sig = _rpt_kernel_signal_words(locale=locale)
    repair_kw = sig["repair"]
    abnormal_kw = sig["abnormal"]
    # heuristic: prefer lines with strong signals
    scored: List[tuple[int, str]] = []
    for ln in lines[-2000:]:
        score = 0
        if "✅" in ln:
            score += 3
        if repair_kw in ln or "fix" in ln.lower():
            score += 2
        if "error" in ln.lower() or abnormal_kw in ln:
            score += 1
        if "warn" in ln.lower() or "warning" in ln.lower():
            score += 1
        if score > 0:
            scored.append((score, ln))
    scored.sort(key=lambda x: -x[0])
    picked = [ln for _, ln in scored[:top_n]]
    if not picked:
        picked = lines[-top_n:]
    out: List[ProviderItem] = []
    for ln in picked[:top_n]:
        out.append(ProviderItem(title=_clip(ln, 80), summary=_clip(ln, 240)))
    return out


async def system_updates_provider(
    *, kernel_log_path: str, top_n: int, locale: Optional[str] = None
) -> Dict[str, Any]:
    items = _top_lines_from_kernel_log(kernel_log_path, top_n=top_n, locale=locale)
    return {"top_n": top_n, "items": [i.__dict__ for i in items], "sources": [kernel_log_path]}


def _items_from_search(results: List[Dict[str, str]], *, top_n: int) -> List[ProviderItem]:
    out: List[ProviderItem] = []
    for r in results[:top_n]:
        title = (r.get("title") or "").strip() or "Untitled"
        href = (r.get("href") or "").strip() or None
        body = (r.get("body") or "").strip()
        out.append(ProviderItem(title=_clip(title, 90), summary=_clip(body, 240), link=href))
    return out


async def last30days_or_search_provider(
    *,
    topic: str,
    top_n: int,
    emit: str = "context",
    sources: str = "auto",
    refresh: bool = False,
    timeout_sec: float = 120.0,
    search_fn: Optional[SearchFn] = None,
    locale: Optional[str] = None,
    enable_cache: bool = True,
    cache_ttl_sec: float = 600.0,
    period_start: Optional[datetime] = None,
    period_end: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Prefer last30days external CLI. If unavailable/fails, fallback to WEB_SEARCH (injected search_fn).

    When ``period_start`` / ``period_end`` 已给出，采集端会将 UTC 闭区间写入 last30days 主题首段，
    并在 Web 回退查询中使用带时间边界的检索语句。
    """
    topic_cli = (
        _build_last30days_topic(topic, period_start=period_start, period_end=period_end)
        if period_start is not None and period_end is not None
        else (topic or "").strip()
    )

    res = await run_last30days(
        topic_cli,
        emit=emit,
        sources=sources,
        refresh=refresh,
        timeout=timeout_sec,
        enable_cache=enable_cache,
        cache_ttl_sec=float(cache_ttl_sec),
        fallback_to_web_search=False,
    )
    if res.get("ok"):
        text = str(res.get("parsed") or "").strip()
        # best-effort: extract markdown bullet-ish lines as items
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        bullets = [ln for ln in lines if ln.startswith(("-", "*", "1.", "2.", "3."))]
        items: List[ProviderItem] = []
        for ln in (bullets or lines)[:top_n]:
            clean = re.sub(r"^\s*[-*]\s*", "", ln).strip()
            items.append(ProviderItem(title=_clip(clean, 220), summary=_clip(clean, 280)))
        if period_start is not None and period_end is not None:
            items = filter_items_by_explicit_calendar_dates(
                items, period_start=period_start, period_end=period_end
            )[:top_n]
        return {
            "top_n": top_n,
            "items": [i.__dict__ for i in items],
            "sources": [
                {
                    "backend": "last30days",
                    "topic": topic_cli,
                    "emit": res.get("emit"),
                    "sources_mode": res.get("sources"),
                }
            ],
            "cache_hit": bool(res.get("cache_hit", False)),
            "error": None,
        }

    if search_fn is None:
        return {
            "top_n": top_n,
            "items": [],
            "sources": [],
            "cache_hit": False,
            "error": res.get("error")
            or {"kind": "no_fallback", "message": "last30days failed and no search_fn provided"},
        }
    tr = default_translator()
    loc = normalize_locale(locale or settings.effective_ui_default_locale())
    if period_start is not None and period_end is not None:
        q = tr.t(
            "rpt.search_bounded_query",
            locale=loc,
            topic=(topic or "").strip(),
            start=_utc_z(period_start),
            end=_utc_z(period_end),
        )
    else:
        suffix = tr.t("rpt.search_fallback_suffix", locale=loc)
        q = f"{(topic or '').strip()} {suffix}"
    lang_hint = tr.t("rpt.search_lang_hint", locale=loc)
    q2 = f"{q} {lang_hint}".strip()
    raw = _filter_stub_search_results(await search_fn(q2, top_n), locale=loc)
    items = _items_from_search(raw, top_n=top_n)
    if period_start is not None and period_end is not None:
        items = filter_items_by_explicit_calendar_dates(
            items, period_start=period_start, period_end=period_end
        )[:top_n]
    return {
        "top_n": top_n,
        "items": [i.__dict__ for i in items],
        "sources": [{"backend": "web_search", "query": q2}],
        "cache_hit": False,
        "error": res.get("error"),
    }


async def crypto_spot_prices_provider(
    *,
    timeout_sec: float = 12.0,
    locale: Optional[str] = None,
) -> Dict[str, Any]:
    """
    CoinGecko 公开 ``simple/price``：BTC / ETH / SOL 对美元现货（无 API Key）。
    失败时返回空 ``items`` 与 ``error`` 说明，由模板展示占位文案。
    """
    loc = normalize_locale(locale or settings.effective_ui_default_locale())
    tr = default_translator()
    if bool(getattr(settings, "ADAMI_SIM_OFFLINE", False)):
        return {
            "items": [],
            "sources": [],
            "error": {"kind": "offline", "message": "ADAMI_SIM_OFFLINE enabled"},
            "error_user": tr.t("report.studio.crypto_fetch_failed", locale=loc, detail="offline")[:160],
        }
    ids = "bitcoin,ethereum,solana"
    url = "https://api.coingecko.com/api/v3/simple/price"
    params = {
        "ids": ids,
        "vs_currencies": "usd",
        "include_24hr_change": "true",
        "include_last_updated_at": "true",
    }
    try:
        import httpx

        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            r = await client.get(url, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        return {
            "items": [],
            "sources": [url],
            "error": {"kind": "crypto_fetch_failed", "message": str(e)},
            "error_user": tr.t(
                "report.studio.crypto_fetch_failed", locale=loc, detail=str(e)[:120]
            ),
        }

    rows: List[Dict[str, Any]] = []
    mapping = (
        ("bitcoin", "BTC", "Bitcoin"),
        ("ethereum", "ETH", "Ethereum"),
        ("solana", "SOL", "Solana"),
    )
    for key, sym, name in mapping:
        row = data.get(key) if isinstance(data, dict) else None
        if not isinstance(row, dict):
            continue
        usd = row.get("usd")
        ch24 = row.get("usd_24h_change")
        ts = row.get("last_updated_at")
        price_disp = f"{float(usd):,.2f}" if isinstance(usd, (int, float)) else ""
        ch_disp = None
        if isinstance(ch24, (int, float)):
            ch_disp = f"{ch24:+.2f}%"
        rows.append(
            {
                "id": key,
                "symbol": sym,
                "name": name,
                "price_usd": usd,
                "price_usd_display": price_disp,
                "change_24h_pct": ch24,
                "change_24h_display": ch_disp,
                "updated_ts": ts,
            }
        )

    if len(rows) < 3:
        return {
            "items": rows,
            "sources": [url],
            "error": {"kind": "crypto_partial", "message": "incomplete payload"},
            "error_user": tr.t("report.studio.crypto_fetch_failed", locale=loc, detail="partial"),
        }

    return {"items": rows, "sources": [url], "error": None, "error_user": None}
