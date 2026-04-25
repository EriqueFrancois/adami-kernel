from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Optional

_REPO = Path(__file__).resolve().parents[4]
_CATALOG_DIR = _REPO / "src" / "adami_kernel" / "i18n" / "catalogs"
_CITIES_PATH = _CATALOG_DIR / "cities.json"
_CRYPTO_PATH = _CATALOG_DIR / "crypto_assets.json"

_RE_WS = re.compile(r"\s+")


def _norm(s: str) -> str:
    t = str(s or "").strip().lower()
    t = _RE_WS.sub(" ", t)
    return t


@lru_cache(maxsize=8)
def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_aliases(aliases: dict[str, list[str]], *, locale: str) -> Iterable[str]:
    out: list[str] = []
    for k in (locale, "zh-Hans", "en"):
        vs = aliases.get(k)
        if isinstance(vs, list):
            out.extend([str(x) for x in vs if str(x).strip()])
    return out


@dataclass(frozen=True)
class ResolvedCity:
    id: str
    country: str
    display_name: str
    api_name: str


@dataclass(frozen=True)
class ResolvedCryptoAsset:
    symbol: str
    display_name: str
    coingecko_id: str


def resolve_city_from_text(text: str, *, locale: str) -> Optional[ResolvedCity]:
    """
    Resolve a city mention from free text using the shipped city catalog.

    Matching is substring-based over locale-specific aliases. This is a pragmatic
    router helper, not full NER.
    """
    raw = str(text or "")
    if not raw.strip():
        return None
    data = _load_json(_CITIES_PATH)
    cities = data.get("cities")
    if not isinstance(cities, list):
        return None

    hay = _norm(raw)
    best: Optional[tuple[int, dict[str, Any]]] = None  # (alias_len, row)
    for row in cities:
        if not isinstance(row, dict):
            continue
        aliases = row.get("aliases")
        if not isinstance(aliases, dict):
            continue
        for a in _iter_aliases(aliases, locale=locale):
            an = _norm(a)
            if not an:
                continue
            if an in hay:
                cand = (len(an), row)
                if best is None or cand[0] > best[0]:
                    best = cand
    if best is None:
        return None
    row = best[1]
    rid = str(row.get("id") or "").strip()
    country = str(row.get("country") or "").strip().upper()
    names = row.get("names") if isinstance(row.get("names"), dict) else {}
    disp = str(names.get(locale) or names.get("zh-Hans") or names.get("en") or rid).strip()
    api_name = disp
    api = row.get("api") if isinstance(row.get("api"), dict) else {}
    om = api.get("open_meteo") if isinstance(api.get("open_meteo"), dict) else {}
    om_name = om.get("name") if isinstance(om.get("name"), dict) else {}
    api_name = str(
        om_name.get(locale) or om_name.get("zh-Hans") or om_name.get("en") or disp
    ).strip()
    if not rid or not disp or not api_name:
        return None
    return ResolvedCity(id=rid, country=country, display_name=disp, api_name=api_name)


def resolve_crypto_asset_from_text(text: str, *, locale: str) -> Optional[ResolvedCryptoAsset]:
    raw = str(text or "")
    if not raw.strip():
        return None
    data = _load_json(_CRYPTO_PATH)
    assets = data.get("assets")
    if not isinstance(assets, list):
        return None
    hay = _norm(raw)
    best: Optional[tuple[int, dict[str, Any]]] = None
    for row in assets:
        if not isinstance(row, dict):
            continue
        aliases = row.get("aliases")
        if not isinstance(aliases, dict):
            continue
        for a in _iter_aliases(aliases, locale=locale):
            an = _norm(a)
            if not an:
                continue
            if an in hay:
                cand = (len(an), row)
                if best is None or cand[0] > best[0]:
                    best = cand
    if best is None:
        return None
    row = best[1]
    sym = str(row.get("symbol") or "").strip().upper()
    cg = str(row.get("coingecko_id") or "").strip()
    names = row.get("names") if isinstance(row.get("names"), dict) else {}
    disp = str(names.get(locale) or names.get("zh-Hans") or names.get("en") or sym).strip()
    if not sym or not cg:
        return None
    return ResolvedCryptoAsset(symbol=sym, display_name=disp, coingecko_id=cg)
