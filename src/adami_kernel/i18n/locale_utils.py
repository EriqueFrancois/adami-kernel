from __future__ import annotations

from typing import Optional, Sequence


def normalize_locale(raw: Optional[str]) -> str:
    """Normalize user-facing locale tags toward BCP 47-ish strings (Module 6 policy)."""
    if raw is None:
        return "en"
    s = str(raw).strip().replace("_", "-")
    if not s:
        return "en"
    parts = s.split("-")
    parts[0] = parts[0].lower()
    s2 = "-".join(parts)
    if s2.lower() in {"zh-cn", "zhcn", "zh_cn"}:
        return "zh-Hans"
    return s2


def pick_first_supported(
    *candidates: Optional[str],
    supported: Sequence[str],
    hard_fallback: str = "en",
) -> str:
    """Return the first candidate that normalizes into ``supported``; else ``hard_fallback``."""
    sup = {normalize_locale(x) for x in supported}
    if hard_fallback not in sup:
        sup.add(normalize_locale(hard_fallback))
    for c in candidates:
        if c is None:
            continue
        s = str(c).strip()
        if not s:
            continue
        n = normalize_locale(s)
        if n in sup:
            return n
    return normalize_locale(hard_fallback)
