from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple

from adami_kernel.i18n.locale_utils import normalize_locale

logger = logging.getLogger("AdamI-i18n")

_JSON_CACHE: Dict[Tuple[str, int | float | None], Dict[str, str]] = {}


def _read_json_string_dict(path: Path) -> Dict[str, str]:
    """Read a JSON object mapping str->str with a tiny mtime-based cache."""
    try:
        st = path.stat()
        mkey: int | float | None = getattr(st, "st_mtime_ns", None) or st.st_mtime
    except OSError:
        mkey = None

    key = (str(path.resolve()), mkey)
    hit = _JSON_CACHE.get(key)
    if hit is not None:
        return hit

    if not path.is_file():
        _JSON_CACHE[key] = {}
        return {}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:  # pragma: no cover
        logger.warning("[i18n] failed to read %s: %s", path, e)
        _JSON_CACHE[key] = {}
        return {}

    if not isinstance(data, dict):
        _JSON_CACHE[key] = {}
        return {}

    out = {str(k): str(v) for k, v in data.items()}
    _JSON_CACHE[key] = out
    return out


@dataclass
class Translator:
    """JSON catalog translator with merge-friendly overrides.

    Fallback order:
    requested locale -> ``en`` -> key string (and optional warning)
    """

    default_locale: str = "en"
    dev_warn_missing: bool = False
    _override_dir: Optional[Path] = None
    _memory_overrides: Dict[str, Dict[str, str]] = field(default_factory=dict)

    def set_override_dir(self, path: Optional[str | os.PathLike[str]]) -> None:
        self._override_dir = Path(path).expanduser() if path else None

    def set_memory_override(self, locale: str, mapping: Mapping[str, str]) -> None:
        loc = normalize_locale(locale)
        cur = dict(self._memory_overrides.get(loc, {}))
        cur.update({str(k): str(v) for k, v in mapping.items()})
        self._memory_overrides[loc] = cur

    def clear_memory_overrides(self) -> None:
        self._memory_overrides.clear()

    def _catalog_paths(self, locale: str) -> list[Path]:
        root = Path(__file__).resolve().parent
        loc = normalize_locale(locale)
        return [root / "locales" / loc / "common.json"]

    def _load_override_file(self, locale: str) -> Dict[str, str]:
        if self._override_dir is None:
            return {}
        p = self._override_dir / f"{normalize_locale(locale)}.json"
        if not p.is_file():
            return {}
        return _read_json_string_dict(p)

    def _lookup_in_locale(self, locale: str, key: str) -> Optional[str]:
        # memory overrides win (useful for tests / ephemeral UI experiments)
        mem = self._memory_overrides.get(normalize_locale(locale), {})
        if key in mem:
            return mem[key]

        disk = self._load_override_file(locale)
        if key in disk:
            return disk[key]

        for catalog in self._catalog_paths(locale):
            m = _read_json_string_dict(catalog)
            if key in m:
                return m[key]
        return None

    def t(self, key: str, *, locale: Optional[str] = None, **kwargs: Any) -> str:
        loc = normalize_locale(locale or self.default_locale)
        chain = [loc, "en"]
        # de-dupe while preserving order
        seen: set[str] = set()
        ordered: list[str] = []
        for x in chain:
            nx = normalize_locale(x)
            if nx not in seen:
                ordered.append(nx)
                seen.add(nx)

        text: Optional[str] = None
        used: Optional[str] = None
        for cand in ordered:
            hit = self._lookup_in_locale(cand, key)
            if hit is not None:
                text = hit
                used = cand
                break

        if text is None:
            if self.dev_warn_missing or os.environ.get("ADAMI_I18N_WARN_MISSING") == "1":
                logger.warning("[i18n] missing key %r (locale=%s)", key, loc)
            text = key
            used = None

        # Safe interpolation: require all placeholders present; do not leak KeyError to callers.
        try:
            return text.format(**kwargs)
        except KeyError as e:
            missing = str(e).strip("'")
            raise ValueError(
                f"i18n format failed for key={key!r} locale={loc!r} "
                f"(used_catalog_locale={used!r}): missing placeholder {missing!r}"
            ) from e


_default = Translator(default_locale="en", dev_warn_missing=False)


def default_translator() -> Translator:
    return _default


def set_default_translator(tr: Translator) -> None:
    global _default
    _default = tr


def t(key: str, *, locale: Optional[str] = None, **kwargs: Any) -> str:
    from adami_kernel.i18n.request_locale import get_request_locale

    eff = locale if locale is not None else get_request_locale()
    return _default.t(key, locale=eff, **kwargs)
