# src/adami_kernel/cortex/intent_adaptive/templates/retrieval_weather.py
"""Preset template for ``retrieval.weather`` — toolbox web search + Markdown (Step 6)."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

import httpx

from adami_kernel.config import settings
from adami_kernel.cortex.intent_adaptive.models import IntentClassificationResult, IntentType
from adami_kernel.cortex.intent_adaptive.name_tables import resolve_city_from_text
from adami_kernel.cortex.intent_adaptive.outcomes import TemplateOutcome
from adami_kernel.cortex.intent_adaptive.template_registry import TemplateExecutionContext
from adami_kernel.cortex.intent_adaptive.templates._web_snippets import plain_lines_from_search_hits
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.request_locale import get_request_locale


def _locale() -> str:
    return get_request_locale() or settings.effective_ui_default_locale() or "en"


def _excerpt(context: TemplateExecutionContext) -> str:
    c = context.classification
    raw = ""
    if c is not None and isinstance(c.slots, dict):
        raw = str(c.slots.get("query_excerpt") or "")
    if not raw.strip():
        raw = context.task_text or ""
    return str(raw).strip()[:800]


_RE_CITY = re.compile(r"([\u4e00-\u9fff]{2,8})(?:市|县|区)?")
_RE_WEATHER_WORD = re.compile(r"(weather|forecast|气温|天气|温度|降雨|下雪|预报)", re.IGNORECASE)
_RE_CN_TOKEN = re.compile(r"[\u4e00-\u9fff]{2,8}")
_RE_OBS = re.compile(r"(?P<city>[\u4e00-\u9fff]{2,8})\s*(?P<temp>-?\d{1,2}(?:\.\d)?)\s*℃")
_RE_BAD_WEATHER_HREF = re.compile(r"(404|view\.inews\.qq\.com/404)", re.IGNORECASE)
_RE_EXPLICIT_CITY = re.compile(r"([\u4e00-\u9fff]{2,8})市")
_TRUST_CITY_MISMATCH_DOMAINS = ("weather.com.cn", "nmc.cn", "cma.gov.cn")


def _normalize_city_token(t: str) -> str:
    s = str(t or "").strip()
    # Strip common prefixes that appear in natural queries.
    for p in ("今天", "现在", "明天", "后天"):
        if s.startswith(p) and len(s) > len(p):
            s = s[len(p) :]
            break
    # Normalize suffixes.
    s = re.sub(r"(市|县|区|省)$", "", s)
    # Special-case Beijing/Shanghai-style forms.
    if s == "北京市":
        s = "北京"
    return s.strip()


_STOP_TOKENS = {
    "查询",
    "今天",
    "现在",
    "明天",
    "后天",
    "北京市",
    "天气",
    "气温",
    "温度",
    "预报",
}

_OPEN_METEO_GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
_OPEN_METEO_FORECAST = "https://api.open-meteo.com/v1/forecast"


async def _fetch_open_meteo_city_latlon(name: str) -> Optional[tuple[float, float, str]]:
    """Public API (no key): Open-Meteo geocoding. Returns None on failure."""
    params = {"name": name, "count": 1, "language": "zh", "format": "json"}
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(_OPEN_METEO_GEOCODE, params=params)
            r.raise_for_status()
            data = r.json()
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list) or not results:
            return None
        row = results[0]
        if not isinstance(row, dict):
            return None
        lat = float(row.get("latitude"))
        lon = float(row.get("longitude"))
        disp = str(row.get("name") or name)
        return lat, lon, disp
    except Exception:
        return None


async def _fetch_open_meteo_current(lat: float, lon: float) -> Optional[dict[str, Any]]:
    """Public API (no key): Open-Meteo forecast current fields. Returns None on failure."""
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,wind_speed_10m,wind_direction_10m",
        "timezone": "Asia/Shanghai",
    }
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(_OPEN_METEO_FORECAST, params=params)
            r.raise_for_status()
            data = r.json()
        cur = data.get("current") if isinstance(data, dict) else None
        return cur if isinstance(cur, dict) else None
    except Exception:
        return None


async def _try_weather_from_public_api(context: TemplateExecutionContext) -> str:
    raw = _excerpt(context)
    loc = _locale()
    resolved = resolve_city_from_text(raw, locale=loc)
    city = resolved.api_name if resolved is not None else (_extract_city_cn(raw) or "北京")
    geo = await _fetch_open_meteo_city_latlon(city)
    if not geo:
        return ""
    lat, lon, disp = geo
    cur = await _fetch_open_meteo_current(lat, lon)
    if not cur:
        return ""
    t = cur.get("temperature_2m")
    ws = cur.get("wind_speed_10m")
    wd = cur.get("wind_direction_10m")
    if t is None and ws is None:
        return ""
    parts = [f"- **{disp} 实况**: {t}℃" if t is not None else f"- **{disp} 实况**"]
    if ws is not None:
        parts[0] += f" · 风速 {ws} km/h"
    if wd is not None:
        parts[0] += f" · 风向 {wd}°"
    parts.append("- **Source**: Open-Meteo (public API)")
    return "\n".join(parts).strip()


def _extract_city_cn(raw: str) -> str:
    """
    Heuristic city extraction for Chinese queries.

    Prefer the **last** 2–8 CJK token before a weather keyword, and filter out common
    non-geo tokens (e.g. "查询", "今天"). This is deliberately simple and should only
    be used to improve web search relevance, not as a strict NER component.
    """
    s = str(raw or "").strip()
    if not s:
        return ""
    # Fast path: explicit "<city>市" pattern.
    m_city = _RE_EXPLICIT_CITY.search(s)
    if m_city:
        t = _normalize_city_token(m_city.group(1))
        if t and t not in _STOP_TOKENS:
            return t
    m_weather = _RE_WEATHER_WORD.search(s)
    if m_weather:
        prefix = s[: m_weather.start()]
        toks = _RE_CN_TOKEN.findall(prefix)
        for tok in reversed(toks):
            t = _normalize_city_token(tok)
            if t in _STOP_TOKENS:
                continue
            if t and t not in _STOP_TOKENS:
                return t
    # fallback: first token-shaped city mention
    m = _RE_CITY.search(s)
    if m:
        t = _normalize_city_token(m.group(1))
        return t if t not in _STOP_TOKENS else ""
    return ""


def _weather_query(context: TemplateExecutionContext) -> str:
    """
    Build a stable CN-friendly query from the user task.

    Avoid passing long full sentences to the search backend (which tends to reduce
    relevance), and bias toward Chinese-localized results.
    """
    excerpt = _excerpt(context)
    raw = str(excerpt if excerpt else (context.task_text or "")).strip()
    loc = _locale()
    resolved = resolve_city_from_text(raw, locale=loc)
    city = resolved.display_name if resolved is not None else _extract_city_cn(raw)
    if city:
        # Prefer "实况/气温/风" over national news pages.
        q = f"{city} 天气 实况 气温 风"
    else:
        q = raw
    return q.strip()[:200]


def _try_extract_cn_observation(hits: object, *, city: str) -> str:
    """Extract a compact 'city temp℃ wind' line from web snippets if present."""
    if not isinstance(hits, list):
        return ""
    want = (city or "").strip()
    for row in hits:
        if not isinstance(row, dict):
            continue
        blob = f"{row.get('title','')}\n{row.get('body','')}\n{row.get('href','')}"
        m = _RE_OBS.search(blob)
        if not m:
            continue
        found_city = m.group("city") if m.groupdict().get("city") else ""
        if want and (want not in found_city) and (want not in blob):
            continue
        temp = m.group("temp")
        # best-effort wind capture (loose)
        wind = ""
        m2 = re.search(r"(东|西|南|北|东北|西北|东南|西南)风\s*\S{0,6}", blob)
        if m2:
            wind = m2.group(0).strip()
        m3 = re.search(r"(微风|\d{1,2}级)", blob)
        extra = ""
        if m3:
            extra = m3.group(0).strip()
        parts = [p for p in [want or found_city, f"{temp}℃", wind, extra] if p]
        return " ".join(dict.fromkeys(parts))  # de-dup keep order
    return ""


class RetrievalWeatherTemplateHandler:
    """Thin handler: slot excerpt → ``WebTool.search`` → Markdown; optional ``call_llm`` fallback."""

    async def match_score(self, classification: IntentClassificationResult) -> float:
        return 1.0 if classification.primary_type == IntentType.RETRIEVAL_WEATHER else 0.0

    async def execute(self, context: TemplateExecutionContext) -> TemplateOutcome:
        loc = _locale()
        excerpt = _excerpt(context)
        query = _weather_query(context)
        parts: list[str] = [
            i18n_t("intent.template.weather_title", locale=loc),
            "",
        ]
        body = ""

        # Prefer public API first (no key). On any failure, fall back to web search.
        try:
            body = await asyncio.wait_for(_try_weather_from_public_api(context), timeout=6.5)
        except Exception:
            body = ""

        if (not body.strip()) and context.web_search is not None and query:
            try:
                hits = await context.web_search(
                    query,
                    max_results=5,
                    timelimit="d",
                    region="zh-cn",
                )
                # Filter obvious non-weather noise (e.g., company registry sites).
                resolved_city = resolve_city_from_text(excerpt, locale=loc)
                city = (
                    resolved_city.display_name
                    if resolved_city is not None
                    else _extract_city_cn(excerpt)
                ).strip()
                city_country = resolved_city.country if resolved_city is not None else ""
                if isinstance(hits, list) and hits:
                    filtered = []
                    for row in hits:
                        if not isinstance(row, dict):
                            continue
                        title = str(row.get("title") or "")
                        body0 = str(row.get("body") or "")
                        href = str(row.get("href") or "")
                        blob = f"{title}\n{body0}\n{href}"
                        low = blob.lower()
                        if href and _RE_BAD_WEATHER_HREF.search(href):
                            continue
                        if "qcc.com" in low or "企查查" in blob:
                            continue
                        # Known noisy sources for city forecasts (long prose, often mismatched).
                        if "windy.app" in low or "ventusky" in low:
                            continue
                        # City mismatch: for CN cities, be strict (avoid "Henan" pages when asking Lanzhou).
                        if city and city not in blob:
                            if city_country == "CN":
                                continue
                            # Non-CN: allow mismatch only from a small set of trusted national portals.
                            if not any(d in low for d in _TRUST_CITY_MISMATCH_DOMAINS):
                                continue
                        # For CN cities, prefer official CN portals; avoid random aggregators.
                        if city_country == "CN":
                            if not any(
                                d in low for d in ("weather.com.cn", "nmc.cn", "cma.gov.cn")
                            ):
                                continue
                        if ("weather" not in low) and ("天气" not in blob) and ("预报" not in blob):
                            continue
                        filtered.append(row)
                    hits = filtered
                # Prefer a compact observation line when present (reduces "news soup").
                obs = _try_extract_cn_observation(hits, city=city)
                if obs:
                    body = f"{city or '天气实况'}: {obs}"
                else:
                    body = plain_lines_from_search_hits(hits, max_items=2, body_max=160)
            except Exception:
                body = ""
        if not body.strip() and context.router_call_llm is not None:
            try:
                prompt = (
                    "Reply in plain text only (no Markdown markers like '#', '-', '*'). "
                    "At most 7 short lines. Provide today's weather summary.\n"
                    f"User:\n{context.task_text[:700]}"
                )
                raw = await context.router_call_llm(
                    prompt,
                    brain_type="action",
                    temperature=0.15,
                    apply_design_output_policy=False,
                    skip_design_output_policy=True,
                )
                body = str(raw or "").strip()
            except Exception:
                body = ""
        if not body.strip():
            body = i18n_t("intent.template.weather_stub", locale=loc, excerpt=excerpt[:240] or "—")
        parts.append(body)
        md = "\n".join(parts).strip()
        return TemplateOutcome(
            reply_markdown=md,
            telemetry={
                "intent_template": IntentType.RETRIEVAL_WEATHER,
                "trace_id": context.trace_id,
                "used_web_search": bool(context.web_search and query),
            },
            handoff_to_dynamic=False,
        )
