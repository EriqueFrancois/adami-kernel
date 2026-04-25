# -*- coding: utf-8 -*-
"""Wave 21: consolidation, skill_factory, prompt, evolution, skill_inspector, skill_metadata, sub_agent."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Union

import pytest

from adami_kernel.i18n.catalog import default_translator

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "wave21_i18n_strings", _ROOT / "scripts" / "wave21_i18n_strings.py"
)
_W21 = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_W21)

WAVE21_KEYS: tuple[str, ...] = tuple(sorted(_W21.WAVE21_KEYS))

_LOCALES_DIR = _ROOT / "src" / "adami_kernel" / "i18n" / "locales"

_FormatKwargs = dict[str, Union[str, int, float]]
_FORMAT_SAMPLES: dict[str, _FormatKwargs] = {
    "hcon.prompt.dream": {"history_json": "[]"},
    "hcon.prompt.preference": {"history_json": "[]"},
    "hcon.console.pref_found": {"count": 2},
    "cprm.block.current_env": {"event_str": "{}"},
    "cprm.fmt.persona_head": {"persona_text": "p"},
    "cevo.err.build_fmt": {"detail": "e"},
    "cevo.msg.hatch_ok": {"skill_name": "S"},
    "cevo.schema.param": {"name": "n"},
    "cevo.tool.dynamic": {"skill_name": "S"},
    "cevo.persona.instincts": {"names": "a, b"},
    "cevo.persona.skills": {"names": "x"},
    "cevo.log.move_missing_src": {"src": "/tmp/x"},
    "sins.prompt.mock_args": {
        "description": "d",
        "code_snippet": "c",
        "args_names": "a,b",
    },
    "csub.console.spawn": {"task_id": "t1", "brain": "LEFT"},
    "csub.console.done": {"task_id": "t1"},
    "csub.console.orchestrate": {"n": 3},
    "csub.prompt.system": {"task_desc": "td", "skills": "[]"},
    "csub.err.brain_dead": {"task_id": "t1"},
    "csub.err.lost": {"task_id": "t1"},
}


def _load_common(locale: str) -> dict[str, str]:
    p = _LOCALES_DIR / locale / "common.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return {str(k): str(v) for k, v in data.items()}


@pytest.mark.parametrize("key", WAVE21_KEYS)
def test_wave21_keys_exist_en_zh(key: str) -> None:
    en = _load_common("en")
    zh = _load_common("zh-Hans")
    assert key in en and en[key].strip()
    assert key in zh and zh[key].strip()


@pytest.mark.parametrize("key,kwargs", list(_FORMAT_SAMPLES.items()))
def test_wave21_format_safe(key: str, kwargs: dict[str, Any]) -> None:
    tr = default_translator()
    for loc in ("en", "zh-Hans"):
        tr.t(key, locale=loc, **kwargs)


def test_wave21_cprm_tail_static_no_placeholders() -> None:
    tr = default_translator()
    for loc in ("en", "zh-Hans"):
        s = tr.t("cprm.tail.static_manual", locale=loc)
        assert "Evolution playbook" in s or "进化模块" in s
        assert len(s) > 500


def test_wave21_bilingual_hcon_pref_found_differs() -> None:
    tr = default_translator()
    k = "hcon.console.pref_found"
    a = tr.t(k, locale="en", count=1)
    b = tr.t(k, locale="zh-Hans", count=1)
    assert a != b
