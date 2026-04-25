# -*- coding: utf-8 -*-
"""Wave 22: template repo, optimizer, run_trainer, washer, tools_manager, agent_models, episodic, tdd, circadian, dream_sandbox."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Union

import pytest

from adami_kernel.i18n.catalog import default_translator

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "wave22_i18n_strings", _ROOT / "scripts" / "wave22_i18n_strings.py"
)
_W22 = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_W22)

WAVE22_KEYS: tuple[str, ...] = tuple(sorted(_W22.WAVE22_KEYS))

_LOCALES_DIR = _ROOT / "src" / "adami_kernel" / "i18n" / "locales"

_FormatKwargs = dict[str, Union[str, int, float]]
_FORMAT_SAMPLES: dict[str, _FormatKwargs] = {
    "stpl.weather.err_congest": {"status_code": 503},
    "stpl.weather.err_net": {"exc_name": "HTTPError"},
    "stpl.price.success": {"coin": "BTC", "amount": "1.23"},
    "stpl.price.err_fetch": {"coin_id": "bitcoin", "status_code": 404},
    "stpl.price.err_net": {"err": "timeout"},
    "sopt.desc.register_fmt": {"new_version": "v1.2", "errors_preview": "e..."},
    "sopt.log.instinct_skip": {"skill_name": "S"},
    "sopt.log.bad_name": {"skill_name": "bad"},
    "sopt.log.start": {"skill_name": "S"},
    "sopt.log.no_errors": {"skill_name": "S"},
    "sopt.log.gen_retry": {"attempt": 1},
    "sopt.log.gen_fail": {"skill_name": "S"},
    "sopt.log.tdd_gen": {"skill_name": "S"},
    "sopt.log.tdd_reject": {"skill_name": "S"},
    "sopt.log.tdd_ok": {"skill_name": "S"},
    "sopt.log.score_cmp": {"new_score": 1.0, "old_score": 0.0},
    "sopt.log.reg_retry": {"attempt": 1},
    "sopt.log.reg_fail": {"feedback": "x"},
    "sopt.log.done": {"skill_name": "S", "new_version": "v2"},
    "sopt.log.missing_file": {"skill_name": "S"},
    "sopt.log.read_old_fail": {"err": "e"},
    "sopt.log.protected": {"skill_name": "S"},
    "sopt.log.tdd_saved": {"path": "tests/t.py"},
    "sopt.log.tdd_result": {"skill_name": "S", "result": "ok"},
    "sopt.log.tdd_exec_fail": {"err": "e"},
    "sopt.log.tier1": {"skill_name": "S"},
    "sopt.log.build_fail": {"detail": "d"},
    "sopt.log.gen_exc": {"err": "e"},
    "sopt.log.deprecated": {"skill_name": "S"},
    "sopt.log.deprecate_fail": {"err": "e"},
    "sopt.prompt.optimize_wrap": {"skill_name": "S", "errors": "err"},
    "rtrn.stderr.agl_missing": {"err": "no module"},
    "swsh.log.validation_fail": {"detail": "d"},
    "swsh.log.done": {"skill_name": "S"},
    "swsh.log.replaced_call": {"call_str": "os.system()"},
    "swsh.fallback.replace_kw": {"kw": "os.system"},
    "swsh.ast_fallback": {"err": "e"},
    "swsh.min.log_exec": {"skill_name": "S"},
    "tlsm.prompt.analyze_raw": {"raw_excerpt": "abc"},
    "tlsm.voice.exc": {"detail": "d"},
    "tlsm.image.exc": {"detail": "d"},
    "tlsm.file.exc": {"detail": "d"},
    "epis.log.init_fail": {"err": "e"},
    "epis.doc.save": {"task": "t", "action": "a", "bad_code": "c", "error_msg": "m"},
    "epis.query.recall": {"current_task": "t", "current_action": "a"},
    "epis.recall.item": {"idx": 1, "doc": "d"},
    "epis.log.saved": {"action": "A"},
    "epis.log.save_fail": {"err": "e"},
    "epis.log.recall_ok": {"n": 2},
    "epis.log.recall_fail": {"err": "e"},
    "stdd.log.start": {"skill_name": "S"},
    "stdd.prompt.body": {
        "skill_name": "S",
        "description": "d",
        "code": "pass",
        "skill_lower": "s",
    },
    "stdd.log.too_short": {"skill_name": "S"},
    "stdd.log.ok": {"skill_name": "S", "n": 100},
    "stdd.log.fail": {"err": "e"},
    "circ.last30.task": {
        "digest_kind": "daily",
        "date": "2026-01-01",
        "topic": "t",
        "args_json": "{}",
    },
    "circ.morning.console": {"prefix": "[P]"},
    "circ.morning.task": {"prefix": "[P]", "date": "2026-01-01"},
    "circ.publish.fail_console": {"err": "e"},
    "circ.gc.dir_fail": {"dir_path": "/tmp", "err": "e"},
    "circ.gc.done": {"n": 3},
    "circ.tick.error": {"err": "e"},
    "drsb.log.docker_attempt": {"attempt": 1, "err": "e"},
    "drsb.err.cmd_timeout": {"timeout": 30},
    "drsb.log.container_rm_fail": {"err": "e"},
    "drsb.log.net_error": {"err": "e"},
    "drsb.err.net_user": {"err": "e"},
    "drsb.log.cmd_exc": {"err": "e"},
    "drsb.log.fallback_exc": {"err": "e"},
}


def _load_common(locale: str) -> dict[str, str]:
    p = _LOCALES_DIR / locale / "common.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return {str(k): str(v) for k, v in data.items()}


@pytest.mark.parametrize("key", WAVE22_KEYS)
def test_wave22_keys_exist_en_zh(key: str) -> None:
    en = _load_common("en")
    zh = _load_common("zh-Hans")
    assert key in en and en[key].strip()
    assert key in zh and zh[key].strip()


@pytest.mark.parametrize("key,kwargs", list(_FORMAT_SAMPLES.items()))
def test_wave22_format_safe(key: str, kwargs: dict[str, Any]) -> None:
    tr = default_translator()
    for loc in ("en", "zh-Hans"):
        tr.t(key, locale=loc, **kwargs)


def test_wave22_bilingual_tlsm_no_router_differs() -> None:
    tr = default_translator()
    k = "tlsm.err.no_router"
    assert tr.t(k, locale="en") != tr.t(k, locale="zh-Hans")
