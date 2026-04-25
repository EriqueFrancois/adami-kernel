# -*- coding: utf-8 -*-
"""Wave 20: cortex RPA / multi_modal / reinforcement / meta_cortex + reflexion + skcg keys."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Union

import pytest

from adami_kernel.i18n.catalog import default_translator

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "wave20_i18n_strings", _ROOT / "scripts" / "wave20_i18n_strings.py"
)
_W20 = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_W20)

WAVE20_KEYS: tuple[str, ...] = tuple(sorted(_W20.WAVE20_EN))

_LOCALES_DIR = _ROOT / "src" / "adami_kernel" / "i18n" / "locales"

_FormatKwargs = dict[str, Union[str, int, float]]
_FORMAT_SAMPLES: dict[str, _FormatKwargs] = {
    "crfn.console.accuracy": {
        "reward": 1.0,
        "accuracy_bonus": 0.0,
        "trend_bonus": 0.0,
    },
    "skcg.prompt.generate_body": {"description": "d"},
    "rpa.browser.page_opened": {"title": "t", "url": "https://x"},
    "rpa.browser.element_clicked": {"selector": "s"},
    "rpa.browser.form_filled": {"selector": "s", "text": "x"},
    "rpa.browser.text_extracted": {"snippet": "ab"},
    "rpa.browser.unknown_action": {"action_type": "x"},
    "rpa.browser.failed": {"detail": "e"},
    "rpa.gui.click_done": {"x": 0, "y": 0},
    "rpa.gui.typewrite_done": {"text": "x"},
    "rpa.gui.hotkey_done": {"text": "x"},
    "rpa.gui.position": {"pos": "(0,0)"},
    "rpa.gui.unknown_action": {"action_type": "x"},
    "rpa.gui.failed": {"detail": "e"},
    "mmodal.voice.task_prefix": {"snippet": "ab"},
    "mmodal.voice.failed": {"detail": "e"},
    "mmodal.image.extract_failed": {"detail": "e"},
    "mmodal.file.missing_unstructured": {"exe": "/usr/bin/python3"},
    "mmodal.file.extract_failed": {"detail": "e"},
    "refl.pause.selftest_failed": {"reward": 0.5},
    "refl.prompt.critique": {
        "task_description": "t",
        "error": "e",
        "history_json": "[]",
    },
    "mcx.prompt.prune": {"rules_text": "- r"},
    "mcx.prompt.plan": {
        "current_persona": "p",
        "endocrine_status": "e",
        "history_str": "h",
        "graph_insight": "",
        "feedback_summary": "",
    },
    "mcx.feedback.line": {
        "skill": "s",
        "status": "ok",
        "score": 1.0,
        "pass_rate": 99,
    },
}


def _load_common(locale: str) -> dict[str, str]:
    p = _LOCALES_DIR / locale / "common.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return {str(k): str(v) for k, v in data.items()}


@pytest.mark.parametrize("key", WAVE20_KEYS)
def test_wave20_keys_exist_en_zh(key: str) -> None:
    en = _load_common("en")
    zh = _load_common("zh-Hans")
    assert key in en and en[key].strip()
    assert key in zh and zh[key].strip()


@pytest.mark.parametrize("key,kwargs", list(_FORMAT_SAMPLES.items()))
def test_wave20_format_safe(key: str, kwargs: dict[str, Any]) -> None:
    tr = default_translator()
    for loc in ("en", "zh-Hans"):
        tr.t(key, locale=loc, **kwargs)


def test_wave20_bilingual_crfn_console_differs() -> None:
    tr = default_translator()
    k = "crfn.console.accuracy"
    a = tr.t(
        k,
        locale="en",
        reward=1.0,
        accuracy_bonus=0.0,
        trend_bonus=0.0,
    )
    b = tr.t(
        k,
        locale="zh-Hans",
        reward=1.0,
        accuracy_bonus=0.0,
        trend_bonus=0.0,
    )
    assert a != b
