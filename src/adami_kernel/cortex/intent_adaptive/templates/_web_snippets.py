# src/adami_kernel/cortex/intent_adaptive/templates/_web_snippets.py
"""Format ``WebTool.search`` rows into compact plain-text lines (no subprocess)."""

from __future__ import annotations

import re
from typing import Any, List

_RE_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_RE_ZW = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff]")
_RE_WS = re.compile(r"\s+")
_RE_BOILERPLATE = re.compile(
    r"(京ICP|公网安备|ICP证|客服电话|客服邮箱|service@|copyright|©|all\s+rights\s+reserved)",
    re.IGNORECASE,
)


def _clean_snippet(text: str, *, max_len: int) -> str:
    """
    Best-effort snippet cleanup for web search results.

    DDG-style backends may return control chars / zero-width joiners or mixed whitespace
    that renders as "character interference" in CLI and Markdown.
    """
    s = str(text or "")
    s = _RE_CONTROL.sub("", s)
    s = _RE_ZW.sub("", s)
    s = _RE_BOILERPLATE.sub("", s)
    s = _RE_WS.sub(" ", s).strip()
    if max_len > 0 and len(s) > max_len:
        s = s[:max_len] + "…"
    return s


def plain_lines_from_search_hits(hits: Any, *, max_items: int = 3, body_max: int = 280) -> str:
    """Turn DDG-style dict rows into plain text lines (no bullets)."""
    if not isinstance(hits, list) or not hits:
        return ""
    lines: List[str] = []
    for row in hits[: max(0, int(max_items))]:
        if not isinstance(row, dict):
            continue
        title = _clean_snippet(str(row.get("title") or ""), max_len=80)
        body = _clean_snippet(str(row.get("body") or ""), max_len=int(body_max))
        if title or body:
            label = title if title else "result"
            if body:
                lines.append(f"{label}: {body}")
            else:
                lines.append(f"{label}")
    return "\n".join(lines)
