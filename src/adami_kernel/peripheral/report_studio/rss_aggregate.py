"""Fetch whitelist RSS feeds, dedupe, time-window, rank, and clip to Top N."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from difflib import SequenceMatcher
from email.utils import parsedate_to_datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

import feedparser
import httpx

logger = logging.getLogger("AdamI-ReportStudio-RSS")

_HTML_TAG_RE = re.compile(r"<[^>]+>")


def _strip_html(s: str) -> str:
    t = _HTML_TAG_RE.sub(" ", s or "")
    return re.sub(r"\s+", " ", t).strip()


def _parse_pub_date(entry: object) -> Optional[datetime]:
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    for attr in ("published", "updated", "created"):
        raw = getattr(entry, attr, None)
        if raw:
            try:
                dt = parsedate_to_datetime(str(raw))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except (TypeError, ValueError, OverflowError):
                continue
    return None


def _canonical_link(url: str) -> str:
    if not (url or "").strip():
        return ""
    p = urlparse(url.strip())
    host = (p.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = (p.path or "").rstrip("/")
    return f"{host}{path}".lower()


def _norm_title(title: str) -> str:
    s = re.sub(r"[^\w\s]", " ", (title or "").lower())
    return re.sub(r"\s+", " ", s).strip()


def _title_similarity(a: str, b: str) -> float:
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return 0.0
    return SequenceMatcher(None, na, nb).ratio()


@dataclass
class RssEntry:
    title: str
    link: str
    summary: str
    published: Optional[datetime]
    source_name: str
    source_url: str

    def as_item_dict(self) -> Dict[str, Any]:
        href = (self.link or "").strip() or None
        return {
            "title": (self.title or "Untitled")[:240],
            "summary": (self.summary or "")[:500],
            "link": href,
        }


@dataclass
class _Cluster:
    rep: RssEntry
    members: List[RssEntry] = field(default_factory=list)

    @property
    def weight(self) -> int:
        return len(self.members)

    @property
    def sort_time(self) -> float:
        if self.rep.published:
            return self.rep.published.timestamp()
        return 0.0


def _in_window(published: Optional[datetime], start: datetime, end: datetime) -> bool:
    if published is None:
        return True
    ps = published.astimezone(timezone.utc)
    return start <= ps <= end


async def _fetch_one_feed(
    client: httpx.AsyncClient, name: str, url: str, *, per_feed_cap: int
) -> List[RssEntry]:
    out: List[RssEntry] = []
    try:
        r = await client.get(url, follow_redirects=True)
        r.raise_for_status()
        parsed = feedparser.parse(r.content)
    except Exception as e:
        logger.warning("[ReportStudio] RSS fetch failed name=%s url=%s err=%s", name, url, e)
        return out

    for entry in getattr(parsed, "entries", [])[:per_feed_cap]:
        title = _strip_html(getattr(entry, "title", "") or "")
        link = ""
        if getattr(entry, "link", None):
            link = str(entry.link).strip()
        else:
            for ln in getattr(entry, "links", []) or []:
                if isinstance(ln, dict) and ln.get("href") and ln.get("rel") in (None, "alternate"):
                    link = str(ln["href"]).strip()
                    break
        summary = ""
        if getattr(entry, "summary", None):
            summary = _strip_html(str(entry.summary))
        elif getattr(entry, "description", None):
            summary = _strip_html(str(entry.description))
        published = _parse_pub_date(entry)
        if not title and not link:
            continue
        out.append(
            RssEntry(
                title=title or "Untitled",
                link=link,
                summary=summary or "",
                published=published,
                source_name=name,
                source_url=url,
            )
        )
    return out


def _cluster_entries(entries: List[RssEntry], *, title_threshold: float = 0.82) -> List[_Cluster]:
    clusters: List[_Cluster] = []
    for e in entries:
        placed = False
        for cl in clusters:
            c_link = _canonical_link(e.link)
            r_link = _canonical_link(cl.rep.link)
            if c_link and r_link and c_link == r_link:
                cl.members.append(e)
                if (e.published or datetime.min.replace(tzinfo=timezone.utc)) > (
                    cl.rep.published or datetime.min.replace(tzinfo=timezone.utc)
                ):
                    cl.rep = e
                placed = True
                break
            if _title_similarity(e.title, cl.rep.title) >= title_threshold:
                cl.members.append(e)
                if (e.published or datetime.min.replace(tzinfo=timezone.utc)) > (
                    cl.rep.published or datetime.min.replace(tzinfo=timezone.utc)
                ):
                    cl.rep = e
                placed = True
                break
        if not placed:
            clusters.append(_Cluster(rep=e, members=[e]))
    return clusters


def _rank_clusters(
    clusters: List[_Cluster],
    *,
    period_start: datetime,
    period_end: datetime,
    top_n: int,
) -> List[RssEntry]:
    ps = period_start.astimezone(timezone.utc)
    pe = period_end.astimezone(timezone.utc)
    kept: List[_Cluster] = []
    for cl in clusters:
        if _in_window(cl.rep.published, ps, pe):
            kept.append(cl)
    kept.sort(key=lambda c: (-c.weight, -c.sort_time))
    return [c.rep for c in kept[:top_n]]


async def aggregate_whitelist_rss(
    feeds: Iterable[Dict[str, str]],
    *,
    period_start: datetime,
    period_end: datetime,
    top_n: int,
    per_feed_cap: int = 25,
    timeout_sec: float = 20.0,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Returns (items as template dicts, sources metadata list).
    """
    feed_list = [{"name": f["name"], "url": f["url"]} for f in feeds if f.get("url")]
    all_entries: List[RssEntry] = []
    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(timeout_sec),
        headers={"User-Agent": "AdamI-ReportStudio/1.0 (+https://github.com)"},
        limits=limits,
    ) as client:
        for f in feed_list:
            entries = await _fetch_one_feed(client, f["name"], f["url"], per_feed_cap=per_feed_cap)
            all_entries.extend(entries)

    all_entries.sort(
        key=lambda e: e.published.timestamp() if e.published else 0.0,
        reverse=True,
    )
    clusters = _cluster_entries(all_entries)
    ranked = _rank_clusters(clusters, period_start=period_start, period_end=period_end, top_n=top_n)
    sources: List[Dict[str, Any]] = [
        {"backend": "rss_whitelist", "feeds": [f["url"] for f in feed_list]}
    ]
    return [e.as_item_dict() for e in ranked], sources
