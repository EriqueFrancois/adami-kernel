# -*- coding: utf-8 -*-
"""Wave 27: skill_loader, temp_workspace, phase_gate, skill_cleaner, train schedule, web manager, mcp config, agl_compat, skill_validator logs, lifecycle, prompt logs, base_nerve, plugin loader, usage mgr, experience_agg, ws, evolution logs, sensitive_filter, health_server, skill_code_generator logs, skill_debug, rpa, cache, deer_flow, docker_stdio_runner, shell, nexus skill_loader, otel."""

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
    "wave27_i18n_strings", _ROOT / "scripts" / "wave27_i18n_strings.py"
)
_W27 = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_W27)

WAVE27_KEYS: tuple[str, ...] = tuple(sorted(_W27.WAVE27_KEYS))

_LOCALES_DIR = _ROOT / "src" / "adami_kernel" / "i18n" / "locales"

_IntNames = frozenset(
    {
        "n",
        "a",
        "th",
        "sec",
        "code",
        "rc",
        "port",
        "typ",
        "pf",
        "cid",
        "mt",
        "nm",
        "fn",
        "attr",
        "eid",
        "cleaned",
        "total",
        "tid",
        "tc",
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
        elif base in ("rw", "elapsed", "tmo", "delay"):
            kw[base] = 1.0
        elif base in ("sb", "pl"):
            kw[base] = "yes"
        else:
            kw[base] = "x"
    return kw


_W27_EN, _W27_ZH = _W27.build_wave27_blobs()
_FORMAT_SAMPLES: dict[str, dict[str, Any]] = {
    k: _kwargs_for_en_template(_W27_EN[k]) for k in WAVE27_KEYS if "{" in _W27_EN[k]
}


def _load_common(locale: str) -> dict[str, str]:
    p = _LOCALES_DIR / locale / "common.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return {str(k): str(v) for k, v in data.items()}


@pytest.mark.parametrize("key", WAVE27_KEYS)
def test_wave27_keys_exist_en_zh(key: str) -> None:
    en = _load_common("en")
    zh = _load_common("zh-Hans")
    assert key in en and en[key].strip()
    assert key in zh and zh[key].strip()


@pytest.mark.parametrize("key,kwargs", list(_FORMAT_SAMPLES.items()))
def test_wave27_format_safe(key: str, kwargs: dict[str, Any]) -> None:
    tr = default_translator()
    for loc in ("en", "zh-Hans"):
        tr.t(key, locale=loc, **kwargs)


def test_wave27_bilingual_sample_differs() -> None:
    tr = default_translator()
    k = "skclr.log.mark_idle"
    assert tr.t(k, locale="en", name="X", ca="y", tc=1) != tr.t(
        k, locale="zh-Hans", name="X", ca="y", tc=1
    )
