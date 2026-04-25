# -*- coding: utf-8 -*-
"""Wave 24: skill_composer, decision_processor, engineer, multi_agent_orchestrator, skill_factory."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from string import Formatter
from typing import Any

import pytest

from adami_kernel.i18n.catalog import default_translator

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "wave24_i18n_strings", _ROOT / "scripts" / "wave24_i18n_strings.py"
)
_W24 = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_W24)

WAVE24_KEYS: tuple[str, ...] = tuple(sorted(_W24.WAVE24_KEYS))

_LOCALES_DIR = _ROOT / "src" / "adami_kernel" / "i18n" / "locales"

_IntNames = frozenset(
    {
        "n",
        "count",
        "attempt",
        "max_retries",
        "code_length",
        "chars",
        "total",
        "rate1",
        "rate2",
        "sec",
    }
)


def _kwargs_for_en_template(tpl: str) -> dict[str, Any]:
    """Build minimal kwargs so ``str.format`` succeeds for every ``{...}`` field in *tpl*."""
    kw: dict[str, Any] = {}
    for _, field_name, _, _ in Formatter().parse(tpl):
        if not field_name or not str(field_name).strip():
            continue
        base = str(field_name).strip()
        if base in kw:
            continue
        if base in _IntNames:
            kw[base] = 1
        elif base == "args":
            kw[base] = {"city": "X"}
        elif base == "keys":
            kw[base] = ["a", "b"]
        elif base == "exists":
            kw[base] = True
        elif base == "result":
            kw[base] = True
        else:
            kw[base] = "x"
    return kw


_W24_EN, _W24_ZH = _W24.build_wave24_blobs()
_FORMAT_SAMPLES: dict[str, dict[str, Any]] = {
    k: _kwargs_for_en_template(_W24_EN[k]) for k in WAVE24_KEYS if "{" in _W24_EN[k]
}


def _load_common(locale: str) -> dict[str, str]:
    p = _LOCALES_DIR / locale / "common.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return {str(k): str(v) for k, v in data.items()}


@pytest.mark.parametrize("key", WAVE24_KEYS)
def test_wave24_keys_exist_en_zh(key: str) -> None:
    en = _load_common("en")
    zh = _load_common("zh-Hans")
    assert key in en and en[key].strip()
    assert key in zh and zh[key].strip()


@pytest.mark.parametrize("key,kwargs", list(_FORMAT_SAMPLES.items()))
def test_wave24_format_safe(key: str, kwargs: dict[str, Any]) -> None:
    tr = default_translator()
    for loc in ("en", "zh-Hans"):
        tr.t(key, locale=loc, **kwargs)


def test_wave24_bilingual_sample_differs() -> None:
    tr = default_translator()
    k = "orch.magent.log.start_multi"
    assert tr.t(k, locale="en") != tr.t(k, locale="zh-Hans")
