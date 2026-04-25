# -*- coding: utf-8 -*-
"""Wave 26: nerve_registry, critic, skill_file_loader, skill_inspector, graph_memory, subconscious, hitl, skill_version_manager, db_helper, pulse, consolidation, dlq, task_evaluator, self_test_engine."""

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
    "wave26_i18n_strings", _ROOT / "scripts" / "wave26_i18n_strings.py"
)
_W26 = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_W26)

WAVE26_KEYS: tuple[str, ...] = tuple(sorted(_W26.WAVE26_KEYS))

_LOCALES_DIR = _ROOT / "src" / "adami_kernel" / "i18n" / "locales"

_IntNames = frozenset(
    {
        "n",
        "ne",
        "nr",
        "rc",
        "ls",
        "le",
        "iu",
        "isc",
        "tu",
        "ts",
        "tp",
        "a",
        "p",
        "c",
        "cf",
        "u",
        "s",
        "ok",
        "sec",
        "tid",
        "total",
        "wid",
    }
)


def _kwargs_for_en_template(tpl: str) -> dict[str, Any]:
    kw: dict[str, Any] = {}
    for _, field_name, _, _ in Formatter().parse(tpl):
        if not field_name or not str(field_name).strip():
            continue
        base = str(field_name).strip()
        if base in kw:
            continue
        if base in _IntNames:
            kw[base] = 1
        elif base == "skills":
            kw[base] = "['X']"
        elif base == "keys":
            kw[base] = "a,b"
        else:
            kw[base] = "x"
    return kw


_W26_EN, _W26_ZH = _W26.build_wave26_blobs()
_FORMAT_SAMPLES: dict[str, dict[str, Any]] = {
    k: _kwargs_for_en_template(_W26_EN[k]) for k in WAVE26_KEYS if "{" in _W26_EN[k]
}


def _load_common(locale: str) -> dict[str, str]:
    p = _LOCALES_DIR / locale / "common.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return {str(k): str(v) for k, v in data.items()}


@pytest.mark.parametrize("key", WAVE26_KEYS)
def test_wave26_keys_exist_en_zh(key: str) -> None:
    en = _load_common("en")
    zh = _load_common("zh-Hans")
    assert key in en and en[key].strip()
    assert key in zh and zh[key].strip()


@pytest.mark.parametrize("key,kwargs", list(_FORMAT_SAMPLES.items()))
def test_wave26_format_safe(key: str, kwargs: dict[str, Any]) -> None:
    tr = default_translator()
    for loc in ("en", "zh-Hans"):
        tr.t(key, locale=loc, **kwargs)


def test_wave26_bilingual_sample_differs() -> None:
    tr = default_translator()
    k = "subc.log.rem_start"
    assert tr.t(k, locale="en") != tr.t(k, locale="zh-Hans")
