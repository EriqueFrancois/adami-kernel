from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from adami_kernel.config import settings
from adami_kernel.hippocampus.second_brain import SecondBrainManager
from adami_kernel.i18n.locale_utils import normalize_locale
from adami_kernel.integration.last30days_bridge import run_last30days


async def _maybe_translate_digest_note(title: str, body_md: str) -> tuple[str, str]:
    """Translate title/body to `effective_ui_default_locale()` when enabled."""
    if not bool(settings.ADAMI_LAST30DAYS_TRANSLATE_DIGEST):
        return title, body_md
    if not bool(settings.ADAMI_TRANSLATE_ENABLED):
        return title, body_md

    tgt = settings.effective_ui_default_locale()
    src = str(settings.ADAMI_LAST30DAYS_DIGEST_SOURCE_LOCALE or "en").strip()
    if normalize_locale(src) == normalize_locale(tgt):
        return title, body_md

    from adami_kernel.i18n.translate import translate_text_async
    from adami_kernel.integration.minimal_openai_chat import one_shot_completion

    async def call_llm(prompt: str) -> str:
        return await one_shot_completion(prompt, temperature=0.15)

    timeout = float(getattr(settings, "ADAMI_TRANSLATE_TIMEOUT_SEC", 30.0))
    new_title = await translate_text_async(
        title,
        target_locale=tgt,
        call_llm=call_llm,
        source_locale=src,
        scenario="last30days_digest_title",
        timeout_sec=timeout,
    )
    new_body = await translate_text_async(
        body_md,
        target_locale=tgt,
        call_llm=call_llm,
        source_locale=src,
        scenario="last30days_digest_body",
        timeout_sec=timeout,
    )
    return new_title, new_body


async def last30days_digest(
    topic: str,
    *,
    refresh: bool = False,
    emit: str = "context",
    write_to: str = "Inbox",
    sources: str = "auto",
    timeout_sec: Optional[float] = None,
) -> dict[str, Any]:
    """Bridge external last30days CLI and write output into SecondBrain."""
    timeout = float(timeout_sec if timeout_sec is not None else settings.ADAMI_LAST30DAYS_TIMEOUT_SEC)
    result = await run_last30days(
        topic=topic,
        emit=emit,
        sources=sources,
        refresh=refresh,
        timeout_sec=timeout,
        fallback_to_web_search=False,
    )
    if not bool(result.get("ok")):
        return {
            "ok": False,
            "note_path": None,
            "summary": None,
            "cache_hit": bool(result.get("cache_hit")),
            "sources_mode": str(result.get("sources_mode") or sources),
            "error": result.get("error") or {"message": "bridge_failed"},
        }

    body = str(result.get("content") or "").strip()
    if not body:
        return {
            "ok": False,
            "note_path": None,
            "summary": None,
            "cache_hit": bool(result.get("cache_hit")),
            "sources_mode": str(result.get("sources_mode") or sources),
            "error": {"message": "empty_output"},
        }

    prefix = str(getattr(settings, "ADAMI_LAST30DAYS_NOTE_PREFIX", "last30days") or "last30days")
    title = f"{prefix}: {topic}".strip()
    title, body = await _maybe_translate_digest_note(title, body)

    sb = SecondBrainManager(root=Path(str(settings.ADAMI_SECOND_BRAIN_ROOT)))
    if write_to.lower() == "resources":
        note_path = sb.write_resource_note(title=title, body=body)
    else:
        note_path = sb.write_inbox_note(title=title, body=body)

    return {
        "ok": True,
        "note_path": str(note_path),
        "summary": str(result.get("summary") or "") or None,
        "cache_hit": bool(result.get("cache_hit")),
        "sources_mode": str(result.get("sources_mode") or sources),
        "error": None,
    }


async def execute(
    *,
    topic: str,
    emit: str = "context",
    write_to: str = "Inbox",
    refresh: bool = False,
    sources: str = "auto",
) -> dict[str, Any]:
    """Skill entrypoint expected by the kernel's skill loader."""
    if not bool(settings.ADAMI_LAST30DAYS_ENABLED):
        return {
            "ok": False,
            "note_path": None,
            "summary": None,
            "cache_hit": False,
            "sources_mode": sources,
            "error": {"message": "module disabled: ADAMI_LAST30DAYS_ENABLED=false"},
        }
    return await last30days_digest(
        topic,
        refresh=refresh,
        emit=emit,
        write_to=write_to,
        sources=sources,
        timeout_sec=float(settings.ADAMI_LAST30DAYS_TIMEOUT_SEC),
    )

