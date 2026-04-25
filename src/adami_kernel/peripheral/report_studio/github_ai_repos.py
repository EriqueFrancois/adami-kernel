"""GitHub REST search (sitewide top stars) + local snapshots for weekly/monthly star velocity."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import aiosqlite
import httpx

from adami_kernel.config import settings

logger = logging.getLogger("AdamI-ReportStudio-GitHubTop")


def _github_stars_db_path() -> str:
    return str(settings.adami_data_dir_path / "report_studio_github_stars.sqlite")


async def _ensure_schema(db: aiosqlite.Connection) -> None:
    await db.execute(
        """
        CREATE TABLE IF NOT EXISTS github_stars (
            full_name TEXT NOT NULL,
            stars INTEGER NOT NULL,
            recorded_at TEXT NOT NULL
        )
        """
    )
    await db.execute(
        "CREATE INDEX IF NOT EXISTS idx_github_stars_name_time ON github_stars(full_name, recorded_at)"
    )
    await db.commit()


async def record_star_snapshots(rows: List[Tuple[str, int]]) -> None:
    if not rows:
        return
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    path = _github_stars_db_path()
    async with aiosqlite.connect(path) as db:
        await _ensure_schema(db)
        await db.executemany(
            "INSERT INTO github_stars (full_name, stars, recorded_at) VALUES (?,?,?)",
            [(fn, int(st), now) for fn, st in rows],
        )
        await db.commit()


async def stars_at_or_before(full_name: str, ts: datetime) -> Optional[int]:
    path = _github_stars_db_path()
    iso = ts.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    async with aiosqlite.connect(path) as db:
        await _ensure_schema(db)
        cur = await db.execute(
            """
            SELECT stars FROM github_stars
            WHERE full_name = ? AND recorded_at <= ?
            ORDER BY recorded_at DESC LIMIT 1
            """,
            (full_name, iso),
        )
        row = await cur.fetchone()
        return int(row[0]) if row else None


async def github_search_top_repositories(
    *,
    query: str,
    per_page: int = 30,
    timeout_sec: float = 25.0,
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    url = "https://api.github.com/search/repositories"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AdamI-ReportStudio/1.0",
    }
    token = getattr(settings, "GITHUB_TOKEN", None)
    if token and str(token).strip():
        headers["Authorization"] = f"Bearer {str(token).strip()}"
    params = {"q": query, "sort": "stars", "order": "desc", "per_page": str(per_page)}
    try:
        async with httpx.AsyncClient(timeout=timeout_sec) as client:
            r = await client.get(url, params=params, headers=headers)
            if r.status_code != 200:
                return [], {
                    "kind": "github_http",
                    "message": f"HTTP {r.status_code}: {r.text[:200]}",
                }
            data = r.json()
            items = data.get("items") if isinstance(data, dict) else None
            if not isinstance(items, list):
                return [], {"kind": "github_parse", "message": "missing items"}
            out: List[Dict[str, Any]] = []
            for it in items:
                if not isinstance(it, dict):
                    continue
                fn = str(it.get("full_name") or "").strip()
                if not fn:
                    continue
                out.append(
                    {
                        "full_name": fn,
                        "html_url": str(it.get("html_url") or "").strip(),
                        "description": (str(it.get("description") or "").strip())[:400],
                        "stargazers_count": int(it.get("stargazers_count") or 0),
                    }
                )
            return out, None
    except Exception as e:
        logger.warning("[ReportStudio] GitHub search failed: %s", e)
        return [], {"kind": "github_error", "message": str(e)}


async def github_ai_repo_items_for_report(
    *,
    report_type: str,
    period_start: datetime,
    period_end: datetime,
    top_n: int,
    search_query: str,
    per_page: int,
) -> Tuple[List[Dict[str, Any]], Optional[str], Optional[Dict[str, Any]]]:
    """
    Returns (template items: title/summary/link, velocity_note, error).

    Snapshots are written **after** delta reads so this run's inserts do not
    satisfy ``stars_at_or_before(period_start)`` for the same window.
    """
    repos, err = await github_search_top_repositories(query=search_query, per_page=per_page)
    if not repos:
        return [], None, err

    velocity_note: Optional[str] = None
    if report_type == "daily":
        picked = repos[:top_n]
    else:
        keys: List[Tuple[int, int, int, Dict[str, Any]]] = []
        for r in repos:
            past = await stars_at_or_before(r["full_name"], period_start)
            cur = int(r["stargazers_count"])
            if past is None:
                keys.append((0, 0, cur, r))
            else:
                keys.append((1, max(0, cur - past), cur, r))
        if all(t[0] == 0 for t in keys):
            velocity_note = "accumulating"
            picked = sorted(repos, key=lambda x: -x["stargazers_count"])[:top_n]
        else:
            keys.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
            picked = [t[3] for t in keys[:top_n]]
            if any(t[0] == 0 for t in keys[:top_n]):
                velocity_note = "partial_history"

    await record_star_snapshots([(r["full_name"], r["stargazers_count"]) for r in repos])

    items: List[Dict[str, Any]] = []
    for r in picked:
        stars = r["stargazers_count"]
        desc = r.get("description") or ""
        summary = f"★ {stars:,}" + (f" — {desc}" if desc else "")
        items.append(
            {
                "title": r["full_name"][:120],
                "summary": summary[:500],
                "link": r.get("html_url") or None,
            }
        )
    return items, velocity_note, err
