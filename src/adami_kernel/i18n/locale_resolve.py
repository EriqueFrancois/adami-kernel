from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

from adami_kernel.i18n.locale_utils import normalize_locale, pick_first_supported

logger = logging.getLogger("AdamI-i18n")


def read_brain_global_locale(brain_root: Optional[Path], relative_json: str) -> Optional[str]:
    """Read ``{"locale": "..."}`` from SecondBrain ``System/working-memory/locale.json`` (or relative path)."""
    if not brain_root:
        return None
    path = brain_root / relative_json
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # pragma: no cover
        logger.warning("[i18n] failed to read brain locale file %s: %s", path, e)
        return None
    if not isinstance(data, dict):
        return None
    raw = data.get("locale")
    if raw is None:
        return None
    s = str(raw).strip()
    return s or None


def load_chat_locale_map(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # pragma: no cover
        logger.warning("[i18n] failed to read chat locale map %s: %s", path, e)
        return {}
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items() if str(v).strip()}


def save_chat_locale_map(path: Path, mapping: Mapping[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(dict(mapping), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def resolve_effective_locale(
    *,
    payload: Mapping[str, Any],
    chat_id: str,
    chat_overrides: Mapping[str, str],
    brain_root: Optional[Path],
    brain_locale_rel: str,
    default_locale: str,
    supported_locales: Sequence[str],
) -> str:
    """Resolution: per-chat override > payload hint > SecondBrain global > env default > en."""
    sup = list(supported_locales)
    chat_key = str(chat_id)
    persisted = chat_overrides.get(chat_key)
    hint = payload.get("locale")
    if hint is not None:
        hint = str(hint).strip() or None
    brain = read_brain_global_locale(brain_root, brain_locale_rel)
    env_d = normalize_locale(default_locale)
    return pick_first_supported(persisted, hint, brain, env_d, "en", supported=sup)


def hint_locale_from_telegram_language_code(code: Optional[str]) -> Optional[str]:
    if not code or not str(code).strip():
        return None
    c = str(code).strip().lower().replace("_", "-")
    if c.startswith("zh"):
        return "zh-Hans"
    return normalize_locale(c)


def hint_locale_from_discord_locale(locale_obj: Any) -> Optional[str]:
    if locale_obj is None:
        return None
    s = str(locale_obj).strip().replace("_", "-")
    if not s:
        return None
    sl = s.lower()
    if sl.startswith("zh"):
        return "zh-Hans"
    return normalize_locale(s)
