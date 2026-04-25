"""Boundary helpers: translate second‑party / external summaries into the UI locale.

Call sites pass ``call_llm`` (typically ``router.call_llm``) so this module stays
decoupled from the kernel. Uses ``translate_text_async`` with scenario
``external_summary`` for audit/caching.
"""

from __future__ import annotations

from typing import Awaitable, Callable, Optional

from adami_kernel.i18n.translate import translate_text_async


async def translate_external_summary_for_ui(
    text: str,
    *,
    target_locale: str,
    call_llm: Callable[[str], Awaitable[str]],
    source_locale: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> str:
    """Translate ``text`` toward ``target_locale`` for display (news snippets, tool blurbs, etc.).

    When ``ADAMI_TRANSLATE_ENABLED`` is false or the call fails, returns the original ``text``.
    """
    return await translate_text_async(
        text,
        target_locale=target_locale,
        call_llm=call_llm,
        source_locale=source_locale,
        scenario="external_summary",
        trace_id=trace_id,
    )
