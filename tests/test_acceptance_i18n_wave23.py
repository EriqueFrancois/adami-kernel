# -*- coding: utf-8 -*-
"""Wave 23: code_quality_scorer, scan_regex, executor, skill_manager, long_task_schema, sim schema, proprioception, recommender, skill_builder, mcp contracts, web_tool, router, vector_store, report_providers."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any, Union

import pytest

from adami_kernel.i18n.catalog import default_translator

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "wave23_i18n_strings", _ROOT / "scripts" / "wave23_i18n_strings.py"
)
_W23 = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_W23)

WAVE23_KEYS: tuple[str, ...] = tuple(sorted(_W23.WAVE23_KEYS))

_LOCALES_DIR = _ROOT / "src" / "adami_kernel" / "i18n" / "locales"

_FormatKwargs = dict[str, Union[str, int, float, bool]]
_FORMAT_SAMPLES: dict[str, _FormatKwargs] = {
    "cqsc.log.score_done": {"skill_name": "S", "total": 90.0},
    "cqsc.log.rule_err": {"err": "e"},
    "cqsc.prompt.review": {"skill_name": "S", "old_snippet": "a", "new_snippet": "b"},
    "cqsc.log.llm_fallback": {"err": "e"},
    "scan.print.done": {"total": 3},
    "scan.print.list_title": {"n": 2},
    "scan.print.list_footer": {"n": 2},
    "exec.log.direct_call": {"skill_name": "S", "args": {}},
    "exec.log.user_task": {"snippet": "hi"},
    "exec.log.router_match": {"skill_name": "S", "args": {}},
    "exec.log.fallback_call": {"skill_name": "S", "args": {}},
    "exec.log.skill_not_loaded": {"skill_name": "S"},
    "exec.log.invoke": {"skill_name": "S", "safe_args": {}},
    "exec.log.done": {"skill_name": "S", "result": "ok"},
    "exec.log.invoke_fail": {"skill_name": "S", "error_msg": "e"},
    "exec.err.skill_missing": {"skill_name": "S"},
    "skmg.log.anthropic_tpl": {"skill_name": "S"},
    "skmg.log.anthropic_fail": {"err": "e"},
    "skmg.log.exists_active": {"skill_name": "S"},
    "skmg.log.lifecycle_recreate": {"skill_name": "S", "old_status": "CREATED"},
    "skmg.log.inspect_fail": {"skill_name": "S", "feedback": "f"},
    "skmg.log.reg_evolution_fail": {"skill_name": "S", "err": "e"},
    "skmg.log.anthropic_protected": {"skill_name": "S"},
    "skmg.log.instinct_add": {"skill_name": "S"},
    "skmg.log.register_ok": {"skill_name": "S"},
    "skmg.log.vs_sync_retry": {"attempt": 1, "err": "e"},
    "skmg.log.vs_sync_fail": {"skill_name": "S", "err": "e"},
    "skmg.log.scoring_paused": {"skill_name": "S", "success": True},
    "skmg.log.protected": {"skill_name": "S"},
    "skmg.log.instinct_auto": {"skill_name": "S"},
    "skmg.log.deprecated": {"skill_name": "S"},
    "skmg.log.parse_meta_fail": {"err": "e"},
    "mcpf.block": {
        "tool_id": "T",
        "description": "d",
        "schema_str": "{}",
    },
    "prop.log.sniff_fail": {"err": "e"},
    "prop.pain.ram": {"pct": 91.0},
    "prop.pain.cpu": {"pct": 86.0},
    "prop.log.pain": {"pain_type": "RAM"},
    "prop.event.task": {"detail": "d"},
    "reco.reason.row": {"target": "t"},
    "reco.log.count": {"n": 2},
    "reco.summary.persona": {"dynamic": 1, "instincts": 2},
    "skbd.log.instinct_skip": {"skill_name": "S"},
    "skbd.log.instinct_missing": {"skill_name": "S"},
    "skbd.log.complete_detected": {"skill_name": "S"},
    "skbd.log.validate_exc": {"err": "e"},
    "skbd.log.bg_sched": {"skill_name": "S", "file_path": "/tmp/x.py"},
    "skbd.log.bg_err": {"err": "e"},
    "skbd.log.micro_ok": {"path": "/tmp/p"},
    "skbd.log.micro_warn": {"err": "e"},
    "skbd.sec.msg": {"kw": "eval("},
    "skbd.tpl.log_err": {"skill_name": "S"},
    "skbd.log.write_fail": {"err": "e"},
    "webt.err.fail_body": {"detail": "d", "backend": "ddgs"},
    "hyrt.log.http_pool": {"timeout": 30.0},
    "hyrt.log.mlx_freed": {"released": 1, "duration_ms": 12.0},
    "hyrt.log.ollama_ok": {"n": 10},
    "hyrt.log.ollama_fail": {"err": "e"},
    "hyrt.log.cloud_fail": {"name": "N", "exc": "HTTPError"},
    "hyrt.log.cloud_dead": {"brain": "ACTION"},
    "hyrt.log.local_fail": {"err": "e"},
    "hyrt.log.close_warn": {"err": "e"},
    "vs.log.init_fail": {"err": "e"},
    "vs.log.cleanup_fail": {"err": "e"},
    "vs.log.clear_fail": {"err": "e"},
    "vs.log.rebuild_fallback": {"n": 3},
    "vs.log.upsert_fail": {"err": "e"},
    "vs.log.empty_get_fail": {"err": "e"},
    "vs.log.fallback_search": {"query": "q"},
    "vs.log.search_fail": {"err": "e"},
    "vs.warn.add_not_init": {"skill_name": "S"},
    "vs.warn.add_init_fail": {"skill_name": "S"},
    "vs.log.add_fallback": {"skill_name": "S"},
    "vs.log.add_ok": {"skill_name": "S"},
    "vs.log.add_fail": {"err": "e"},
    "vs.log.remove_fail": {"err": "e"},
}


def _load_common(locale: str) -> dict[str, str]:
    p = _LOCALES_DIR / locale / "common.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return {str(k): str(v) for k, v in data.items()}


@pytest.mark.parametrize("key", WAVE23_KEYS)
def test_wave23_keys_exist_en_zh(key: str) -> None:
    en = _load_common("en")
    zh = _load_common("zh-Hans")
    assert key in en and en[key].strip()
    assert key in zh and zh[key].strip()


@pytest.mark.parametrize("key,kwargs", list(_FORMAT_SAMPLES.items()))
def test_wave23_format_safe(key: str, kwargs: dict[str, Any]) -> None:
    tr = default_translator()
    for loc in ("en", "zh-Hans"):
        tr.t(key, locale=loc, **kwargs)


def test_wave23_bilingual_hyrt_all_down_differs() -> None:
    tr = default_translator()
    k = "hyrt.err.all_down"
    assert tr.t(k, locale="en") != tr.t(k, locale="zh-Hans")
