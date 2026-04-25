# Design-output policy loader (awesome-design-systems discipline → LLM prompts).
"""Load ``docs/design_output_policy.md`` for ``HybridLLMRouter.call_llm(..., apply_design_output_policy=True)``."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from adami_kernel.config import settings

logger = logging.getLogger("AdamI-DesignOutputPolicy")

_CACHE_MTIME: Optional[float] = None
_CACHE_BODY: str = ""

_FALLBACK = (
    "Follow clear Markdown structure (headings, bullets), consistent terminology, "
    "and locale-appropriate tone. Reference design-system best practices per "
    "https://github.com/alexpate/awesome-design-systems ."
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _policy_path() -> Path:
    rel = getattr(settings, "ADAMI_DESIGN_OUTPUT_POLICY_PATH", None)
    if rel and str(rel).strip():
        p = Path(str(rel).strip()).expanduser()
        if p.is_absolute():
            return p
        return (_repo_root() / p).resolve()
    return (_repo_root() / "docs" / "design_output_policy.md").resolve()


def load_design_output_policy_text(*, max_chars: int = 8000) -> str:
    """Return trimmed policy text; empty when disabled."""
    global _CACHE_MTIME, _CACHE_BODY
    if not bool(getattr(settings, "ADAMI_DESIGN_OUTPUT_POLICY_ENABLED", True)):
        return ""
    path = _policy_path()
    try:
        st = path.stat().st_mtime
    except OSError as e:
        logger.warning("[design.policy] missing file=%s err=%s", path, e)
        return _FALLBACK[:max_chars]

    if _CACHE_MTIME == st and _CACHE_BODY:
        return _CACHE_BODY[:max_chars]

    try:
        raw = path.read_text(encoding="utf-8").strip()
    except OSError as e:
        logger.warning("[design.policy] read failed file=%s err=%s", path, e)
        body = _FALLBACK
    else:
        body = raw if raw else _FALLBACK

    _CACHE_MTIME = st
    _CACHE_BODY = body
    return body[:max_chars]


def prefix_prompt_with_design_policy(prompt: str) -> str:
    """Prepend policy so all router LLM turns share the same output contract."""
    block = load_design_output_policy_text()
    if not block:
        return prompt
    return (
        '<DESIGN_OUTPUT_POLICY priority="high">\n'
        f"{block}\n"
        "</DESIGN_OUTPUT_POLICY>\n\n"
        f"{prompt}"
    )


def invalidate_design_output_policy_cache() -> None:
    """Test hook: force re-read from disk on next load."""
    global _CACHE_MTIME, _CACHE_BODY
    _CACHE_MTIME = None
    _CACHE_BODY = ""
