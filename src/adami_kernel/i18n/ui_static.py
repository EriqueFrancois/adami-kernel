"""UI strings for contexts without a per-request locale (nerves, shell).

Uses ``settings.effective_ui_default_locale()`` so Telegram/Discord/CLI follow
the configured UI language (e.g. ``ADAMI_UI_LOCALE`` / brain overrides).
"""

from __future__ import annotations

from typing import Any, Dict, FrozenSet, Tuple

from adami_kernel.config import settings
from adami_kernel.i18n.catalog import default_translator


def ui_t(key: str, **kwargs: Any) -> str:
    return default_translator().t(key, locale=settings.effective_ui_default_locale(), **kwargs)


def port_filler_phrases() -> Tuple[str, ...]:
    """Locale-agnostic union (same catalog string in en/zh-Hans) for filler detection."""
    loc = settings.effective_ui_default_locale()
    return tuple(
        x.strip()
        for x in default_translator().t("port.detection.filler_phrases", locale=loc).split("|")
        if x.strip()
    )


def port_filler_exempt_markers() -> Tuple[str, ...]:
    loc = settings.effective_ui_default_locale()
    return tuple(
        x.strip()
        for x in default_translator().t("port.detection.filler_exempt", locale=loc).split("|")
        if x.strip()
    )


def is_entry_menu_command(text: str) -> bool:
    """True for ``/menu``, ``/menu@BotName``, or plain ``menu`` (CLI convenience)."""
    raw = (text or "").strip()
    if not raw:
        return False
    low = raw.lower()
    if low == "menu":
        return True
    if low.startswith("/menu"):
        return low.split("@", 1)[0] == "/menu"
    return False


def port_report_text_triggers() -> FrozenSet[str]:
    """Text aliases to open Report wizard (ASCII + localized aliases)."""
    tr = default_translator()
    loc = settings.effective_ui_default_locale()
    extras = [
        tr.t("port.report.text_alias_report", locale=loc),
        tr.t("port.report.text_alias_sheet", locale=loc),
    ]
    base = ("report:wizard", "/report wizard", "/report config")
    return frozenset(x for x in (*base, *extras) if x and str(x).strip())


def _phrase_in_text(text: str, phrase: str) -> bool:
    if not phrase:
        return False
    if phrase.isascii():
        return phrase.lower() in text.lower()
    return phrase in text


def catalog_pipe_tokens(key: str) -> Tuple[str, ...]:
    """Split a ``key|key`` style catalog string using the effective UI default locale."""
    loc = settings.effective_ui_default_locale()
    raw = default_translator().t(key, locale=loc)
    return tuple(x.strip() for x in raw.split("|") if x.strip())


def task_matches_pipe_catalog(task: str, catalog_key: str) -> bool:
    """True if ``task`` contains any token from a pipe-separated catalog list."""
    from adami_kernel.i18n.request_locale import get_request_locale

    tr = default_translator()
    loc = get_request_locale() or settings.effective_ui_default_locale()
    raw = tr.t(catalog_key, locale=loc)
    for part in raw.split("|"):
        k = (part or "").strip()
        if not k:
            continue
        if k.isascii():
            if k.lower() in task.lower():
                return True
        elif k in task:
            return True
    return False


def catalog_synonym_map(key: str = "sr.synonym_pairs") -> Dict[str, str]:
    """Parse ``zh:en|...`` pairs from a catalog string."""
    out: Dict[str, str] = {}
    for piece in catalog_pipe_tokens(key):
        if ":" not in piece:
            continue
        a, b = piece.split(":", 1)
        out[a.strip()] = b.strip()
    return out


def port_is_filler_reply_for_log(text: str) -> bool:
    """Short replies that look like filler and contain no exempt markers (log-only)."""
    stripped = (text or "").strip()
    if len(stripped) >= 60:
        return False
    if not any(_phrase_in_text(stripped, p) for p in port_filler_phrases()):
        return False
    if any(_phrase_in_text(stripped, p) for p in port_filler_exempt_markers()):
        return False
    return True
