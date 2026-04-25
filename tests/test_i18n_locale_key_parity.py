"""Shipped locale catalogs must define the same keys (parity across common.json)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

_LOCALES_ROOT = Path(__file__).resolve().parents[1] / "src" / "adami_kernel" / "i18n" / "locales"


def _load_common(locale_dir: Path) -> dict[str, str]:
    p = locale_dir / "common.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(data, dict), p
    return {str(k): str(v) for k, v in data.items()}


def _shipped_locale_dirs() -> list[Path]:
    if not _LOCALES_ROOT.is_dir():
        pytest.skip("locales root missing")
    dirs = sorted(
        d for d in _LOCALES_ROOT.iterdir() if d.is_dir() and (d / "common.json").is_file()
    )
    assert dirs, "expected at least one locale with common.json"
    return dirs


def test_common_json_key_parity_across_shipped_locales() -> None:
    dirs = _shipped_locale_dirs()
    key_sets = [_load_common(d).keys() for d in dirs]
    first = set(key_sets[0])
    for d, ks in zip(dirs[1:], key_sets[1:], strict=False):
        missing = first - set(ks)
        extra = set(ks) - first
        assert not missing and not extra, (
            f"locale {d.name} differs from {dirs[0].name}: "
            f"missing={sorted(missing)[:20]!s} extra={sorted(extra)[:20]!s}"
        )
