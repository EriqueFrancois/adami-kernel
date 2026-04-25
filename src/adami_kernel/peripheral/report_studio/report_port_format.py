"""Format fixed-block report bodies for IM-style ports (CLI / Discord / Telegram).

Markdown is kept as-is for SecondBrain notes (``body_md``). Chat pushes call
:func:`plain_report_text_for_im_channels` so ``#`` / ``##`` headings and ``*`` /
``-`` list markers do not read as placeholder noise in plain-text channels.
"""

from __future__ import annotations

import re
from typing import List

_HR_LINE = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
_HEADING = re.compile(r"^(\s{0,3})(#{1,6})\s+(.*)$")
_LIST_LINE = re.compile(r"^(\s*)[-*+]\s+(.*)$")


def _strip_blockquote_prefixes(line: str) -> str:
    s = line
    while True:
        if s.startswith("> "):
            s = s[2:]
        elif s.startswith(">"):
            s = s[1:]
        else:
            break
    return s


def _strip_inline_bold(md: str) -> str:
    out = md
    while True:
        nxt = re.sub(r"\*\*([^*]+)\*\*", r"\1", out)
        if nxt == out:
            break
        out = nxt
    return out


def _strip_markdown_links(md: str) -> str:
    return re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r"\1 (\2)", md)


def plain_report_text_for_im_channels(markdown: str) -> str:
    """Drop ATX headings, list markers, horizontal rules, bold, and link syntax."""
    text = (markdown or "").replace("\r\n", "\n")
    out_lines: List[str] = []
    for raw in text.split("\n"):
        if _HR_LINE.match(raw):
            out_lines.append("")
            continue
        m = _HEADING.match(raw)
        if m:
            out_lines.append(m.group(1) + (m.group(3) or "").strip())
            continue
        s = _strip_blockquote_prefixes(raw)
        lm = _LIST_LINE.match(s)
        if lm:
            s = lm.group(1) + (lm.group(2) or "").strip()
        out_lines.append(s)
    joined = "\n".join(out_lines)
    joined = _strip_inline_bold(joined)
    joined = _strip_markdown_links(joined)
    joined = re.sub(r"\n{4,}", "\n\n\n", joined)
    return joined.strip()
