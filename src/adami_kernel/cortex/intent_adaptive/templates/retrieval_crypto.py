# src/adami_kernel/cortex/intent_adaptive/templates/retrieval_crypto.py
"""Preset template for ``retrieval.crypto`` — toolbox web search + plain text (Step 6)."""

from __future__ import annotations

import asyncio
import re
from typing import Any, Optional

import httpx

from adami_kernel.config import settings
from adami_kernel.cortex.intent_adaptive.models import IntentClassificationResult, IntentType
from adami_kernel.cortex.intent_adaptive.name_tables import resolve_crypto_asset_from_text
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


_RE_BTC = re.compile(r"(btc|bitcoin|比特币)", re.IGNORECASE)
_RE_ETH = re.compile(r"(eth|ethereum|以太坊)", re.IGNORECASE)
_RE_MONEY = re.compile(r"(?i)(?:\\$|usd\\b)\\s*([0-9]{1,3}(?:,[0-9]{3})*(?:\\.[0-9]+)?)")
_RE_BAD_CRYPTO = re.compile(
    r"(?i)(prediction|news|analysis|february\\s+20\\d{2}|in\\s+february|future\\s+date)"
)

_COINGECKO_SIMPLE_PRICE = "https://api.coingecko.com/api/v3/simple/price"


async def _fetch_coingecko_simple_price(*, coin_id: str, vs: list[str]) -> Optional[dict[str, Any]]:
    """Public API (no key): CoinGecko simple price. Returns None on failure."""
    params = {"ids": coin_id, "vs_currencies": ",".join(vs)}
    try:
        async with httpx.AsyncClient(timeout=6.0) as client:
            r = await client.get(_COINGECKO_SIMPLE_PRICE, params=params)
            r.raise_for_status()
            data = r.json()
        if not isinstance(data, dict) or coin_id not in data or not isinstance(data[coin_id], dict):
            return None
        return data[coin_id]
    except Exception:
        return None


def _fmt_money(v: object) -> str:
    try:
        f = float(v)  # type: ignore[arg-type]
    except Exception:
        return ""
    if f >= 1000:
        return f"{f:,.2f}"
    if f >= 1:
        return f"{f:.2f}"
    return f"{f:.6f}"


async def _try_price_from_public_api(context: TemplateExecutionContext) -> str:
    raw = _excerpt(context)
    loc = _locale()
    asset = resolve_crypto_asset_from_text(raw, locale=loc)
    if asset is None:
        return ""
    payload = await _fetch_coingecko_simple_price(coin_id=asset.coingecko_id, vs=["usd", "cny"])
    if not payload:
        return ""
    usd = _fmt_money(payload.get("usd"))
    cny = _fmt_money(payload.get("cny"))
    if not usd and not cny:
        return ""
    label = asset.symbol
    lines: list[str] = []
    if usd:
        lines.append(f"{label} (USD): ${usd}")
    if cny:
        lines.append(f"{label} (CNY): ¥{cny}")
    lines.append("Source: CoinGecko (public API)")
    return "\n".join(lines).strip()


def _crypto_query(context: TemplateExecutionContext) -> str:
    """
    Build a short, high-signal query for search backends.

    This reduces noisy characters and improves relevance for price lookups.
    """
    excerpt = _excerpt(context)
    raw = str(excerpt if excerpt else (context.task_text or "")).strip()
    loc = _locale()
    asset = resolve_crypto_asset_from_text(raw, locale=loc)
    if asset is not None:
        return f"{asset.symbol} price USD"
    # Fall back to original text but keep it short.
    return raw[:200]


class RetrievalCryptoTemplateHandler:
    """Thin handler: slot excerpt → ``WebTool.search`` → Markdown; optional ``call_llm`` fallback."""

    async def match_score(self, classification: IntentClassificationResult) -> float:
        return 1.0 if classification.primary_type == IntentType.RETRIEVAL_CRYPTO else 0.0

    async def execute(self, context: TemplateExecutionContext) -> TemplateOutcome:
        loc = _locale()
        excerpt = _excerpt(context)
        query = _crypto_query(context)
        parts: list[str] = [
            i18n_t("intent.template.crypto_title", locale=loc),
            "",
        ]
        body = ""

        # Prefer public API first (no key). On any failure, fall back to web search.
        try:
            body = await asyncio.wait_for(_try_price_from_public_api(context), timeout=6.5)
        except Exception:
            body = ""

        if (not body.strip()) and context.web_search is not None and query:
            try:
                hits = await context.web_search(
                    query,
                    max_results=6,
                    timelimit="d",
                    region="zh-cn",
                )
                # Filter noisy results (predictions/news/future-date pages) and prefer price-like rows.
                if isinstance(hits, list) and hits:
                    filtered = []
                    for row in hits:
                        if not isinstance(row, dict):
                            continue
                        title = str(row.get("title") or "")
                        body0 = str(row.get("body") or "")
                        href = str(row.get("href") or "")
                        blob = f"{title}\n{body0}\n{href}"
                        if _RE_BAD_CRYPTO.search(blob):
                            continue
                        # 404-ish
                        if "404" in href:
                            continue
                        filtered.append(row)
                    hits = filtered

                # Try to extract a single USD price from the best snippet.
                price = ""
                src_title = ""
                src_href = ""
                if isinstance(hits, list):
                    for row in hits:
                        if not isinstance(row, dict):
                            continue
                        blob = f"{row.get('title','')}\n{row.get('body','')}"
                        m = _RE_MONEY.search(blob)
                        if not m:
                            continue
                        price = m.group(1)
                        src_title = str(row.get("title") or "").strip()
                        src_href = str(row.get("href") or "").strip()
                        break

                if price:
                    lines = [f"BTC (USD): ${price}"]
                    if src_href:
                        t = src_title or "source"
                        lines.append(f"Source: {t} ({src_href})")
                    body = "\n".join(lines)
                else:
                    body = plain_lines_from_search_hits(hits, max_items=3, body_max=180)
            except Exception:
                body = ""
        if not body.strip() and context.router_call_llm is not None:
            try:
                prompt = (
                    "Reply in plain text only (no Markdown markers like '#', '-', '*'). "
                    "At most 7 short lines. Provide current price context if possible.\n"
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
            body = i18n_t("intent.template.crypto_stub", locale=loc, excerpt=excerpt[:240] or "—")
        parts.append(body)
        md = "\n".join(parts).strip()
        return TemplateOutcome(
            reply_markdown=md,
            telemetry={
                "intent_template": IntentType.RETRIEVAL_CRYPTO,
                "trace_id": context.trace_id,
                "used_web_search": bool(context.web_search and query),
            },
            handoff_to_dynamic=False,
        )
