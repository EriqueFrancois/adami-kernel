"""
Single source for AdamI system slash commands (see ``i18n/data/system_commands_manifest.json``).

Used by Telegram ``setMyCommands`` and Discord Application Command registration.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Tuple

_MANIFEST_PATH = (
    Path(__file__).resolve().parents[1] / "i18n" / "data" / "system_commands_manifest.json"
)


@lru_cache(maxsize=1)
def load_system_commands_manifest() -> Dict[str, Any]:
    raw = _MANIFEST_PATH.read_text(encoding="utf-8")
    return json.loads(raw)


def _desc(entry: Dict[str, Any], locale: str) -> str:
    loc = (locale or "en").split("-", 1)[0].lower()
    if loc.startswith("zh"):
        s = str(entry.get("description_zh") or entry.get("description_en") or "").strip()
    else:
        s = str(entry.get("description_en") or entry.get("description_zh") or "").strip()
    if len(s) > 250:
        s = s[:247] + "…"
    return s or "AdamI"


def telegram_command_entries(locale: str) -> List[Tuple[str, str]]:
    """Pairs (command_name, description) for Telegram BotCommand (ASCII names only)."""
    m = load_system_commands_manifest()
    out: List[Tuple[str, str]] = []
    seen: set[str] = set()
    for row in m.get("commands") or []:
        name = row.get("telegram_command")
        if not name or not isinstance(name, str):
            continue
        n = name.strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", n):
            continue
        if n in seen:
            continue
        seen.add(n)
        out.append((n, _desc(row, locale)))
    return out


def markdown_reference(locale: str) -> str:
    """Human-readable block (e.g. for /adamih or docs tooling)."""
    m = load_system_commands_manifest()
    lines = [
        "## AdamI system commands",
        "",
        m.get("document", "").strip(),
        "",
    ]
    for row in m.get("commands") or []:
        ex = row.get("examples") or []
        ex_s = " · ".join(str(x) for x in ex[:4]) if ex else ""
        d = _desc(row, locale)
        sid = str(row.get("id") or "")
        slash = str(row.get("slash") or "")
        lines.append(f"- **{sid}** `{slash}` — {d}")
        if ex_s:
            lines.append(f"  - e.g. {ex_s}")
    return "\n".join(lines)


def discord_slash_specs(locale: str) -> List[Dict[str, Any]]:
    """Rows with discord_register true; includes callback hint fields."""
    m = load_system_commands_manifest()
    out: List[Dict[str, Any]] = []
    for row in m.get("commands") or []:
        if not row.get("discord_register"):
            continue
        tid = row.get("telegram_command")
        if not tid or not isinstance(tid, str):
            continue
        name = tid.strip().lower()
        if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", name):
            continue
        out.append(
            {
                "name": name,
                "description": _desc(row, locale)[:100],
                "id": row.get("id"),
            }
        )
    return out
