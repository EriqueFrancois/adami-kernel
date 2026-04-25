# -*- coding: utf-8 -*-
"""Wave 3 (batch 1): skill.* / market.* / web.* catalog keys."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adami_kernel.i18n.catalog import default_translator

_LOCALES_DIR = Path(__file__).resolve().parents[1] / "src" / "adami_kernel" / "i18n" / "locales"

WAVE3_KEYS: tuple[str, ...] = (
    "skill.validator.empty_code",
    "skill.validator.ast_failed",
    "skill.validator.syntax_context",
    "skill.validator.dangerous",
    "skill.validator.execute_kwargs",
    "skill.validator.execute_not_found",
    "skill.validator.signature_parse",
    "skill.validator.suggestion_syntax",
    "skill.validator.suggestion_security",
    "skill.validator.suggestion_signature",
    "skill.mgr.inspect_failed_default",
    "skill.mgr.register_system_failed",
    "skill.mgr.register_failed_default",
    "market.list.installed_builtin",
    "market.list.unknown_time",
    "market.list.no_description",
    "market.list.last_used_unknown",
    "market.list.desc_dynamic_default",
    "market.list.desc_instinct_default",
    "market.error.skill_already_installed",
    "market.error.github_code_invalid",
    "market.error.melt_failed",
    "market.error.create_skill_failed",
    "market.error.name_code_empty",
    "market.error.skill_exists",
    "market.upload.success_message",
    "market.install.description_from",
    "market.upload.description_user",
    "market.recommend.reason",
    "market.stats.never",
    "market.api.skillmarket_not_initialized",
    "market.api.github_not_initialized",
    "market.api.list_skills_failed",
    "market.api.recommend_failed",
    "market.api.github_search_failed",
    "market.api.install_ok",
    "market.api.install_failed",
    "market.api.upload_failed",
    "market.api.upload_failed_detail",
    "market.api.delete_deleted",
    "market.api.delete_failed",
    "web.dashboard.memory_unavailable",
    "web.dashboard.memory_loaded",
    "web.dashboard.proprioception_ok",
    "web.dashboard.uptime_ok",
    "web.delete.market_missing",
    "web.delete.instinct_forbidden",
    "web.delete.dynamic_missing",
    "web.delete.done",
    "web.delete.failed",
    "web.evolution.scheduler_missing",
    "web.evolution.triggered",
    "skill.builder.suggest_security_retry",
    "skill.builder.write_failed",
    "skill.builder.suggest_disk",
    "skill.builder.validator_failed",
    "skill.builder.suggest_validator_version",
    "skill.inspect.retry_exhausted",
    "skill.inspect.suggest_resubmit_after_feedback",
    "skill.inspect.passed_all",
    "skill.inspect.name_invalid",
    "skill.inspect.suggest_uppercase_name",
    "skill.inspect.name_too_short",
    "skill.inspect.suggest_longer_name",
    "skill.inspect.name_too_long",
    "skill.inspect.suggest_shorter_name",
    "skill.inspect.syntax_error",
    "skill.inspect.suggest_fix_syntax",
    "skill.inspect.require_execute_fn",
    "skill.inspect.suggest_add_execute",
    "skill.inspect.no_asyncio_run",
    "skill.inspect.suggest_no_asyncio_run",
    "skill.inspect.security_blocked",
    "skill.inspect.suggest_remove_unsafe",
    "skill.inspect.exec_returned_none",
    "skill.inspect.suggest_return_dict",
    "skill.inspect.exec_not_dict",
    "skill.inspect.suggest_return_dict_shape",
    "skill.inspect.missing_status_key",
    "skill.inspect.suggest_add_status_key",
    "skill.inspect.bad_status_value",
    "skill.inspect.suggest_fix_status_value",
    "skill.inspect.error_status_missing_error_key",
    "skill.inspect.suggest_add_error_key",
    "skill.inspect.no_execute_callable",
    "skill.inspect.suggest_define_execute",
    "skill.inspect.load_runtime_failed",
    "skill.inspect.suggest_fix_runtime",
    "skill.inspect.mock_ok_no_args",
    "skill.inspect.sandbox_network_blocked",
    "skill.inspect.sandbox_net_tip1",
    "skill.inspect.sandbox_net_tip2",
    "skill.inspect.sandbox_net_tip3",
    "skill.inspect.sandbox_unknown",
    "skill.inspect.skill_run_failed",
    "skill.inspect.status_not_success",
    "skill.inspect.bad_payload_format",
    "skill.inspect.sandbox_gave_up",
    "skill.inspect.suggest_double_braces",
    "skill.inspect.sandbox_crashed",
    "skill.inspect.sandbox_crash_suggest",
    "skill.inspect.sandbox_ok",
    "skill.inspect.host_ok",
    "skill.inspect.host_failed",
    "skill.inspect.host_fail_suggest",
)

_FORMAT_SAMPLES: dict[str, dict[str, str]] = {
    "skill.validator.ast_failed": {"detail": "e"},
    "skill.validator.syntax_context": {"message": "m", "context": "c"},
    "skill.validator.dangerous": {"kw": "os.system"},
    "skill.validator.signature_parse": {"detail": "e"},
    "skill.mgr.register_system_failed": {"detail": "e"},
    "market.error.skill_already_installed": {"skill_name": "X"},
    "market.error.skill_exists": {"skill_name": "X"},
    "market.upload.success_message": {"skill_name": "X"},
    "market.install.description_from": {"source": "github"},
    "market.upload.description_user": {"skill_name": "X"},
    "market.recommend.reason": {"target": "T"},
    "market.api.upload_failed_detail": {"detail": "x"},
    "market.api.delete_deleted": {"name": "n"},
    "market.api.delete_failed": {"name": "n"},
    "web.delete.instinct_forbidden": {"name": "n"},
    "web.delete.dynamic_missing": {"name": "n"},
    "web.delete.done": {"name": "n"},
    "web.delete.failed": {"name": "n"},
    "skill.builder.write_failed": {"skill_name": "X"},
    "skill.builder.validator_failed": {"exc_type": "E", "detail": "d"},
    "skill.inspect.retry_exhausted": {"max_retries": 3},
    "skill.inspect.name_invalid": {"skill_name": "bad"},
    "skill.inspect.name_too_short": {"skill_name": "AB", "length": "2", "min_len": "3"},
    "skill.inspect.name_too_long": {"skill_name": "A" * 50, "length": "50", "max_len": "40"},
    "skill.inspect.syntax_error": {"detail": "e"},
    "skill.inspect.exec_returned_none": {"skill_name": "S"},
    "skill.inspect.exec_not_dict": {"typ": "list", "skill_name": "S"},
    "skill.inspect.missing_status_key": {"skill_name": "S"},
    "skill.inspect.bad_status_value": {"status": "pending", "skill_name": "S"},
    "skill.inspect.error_status_missing_error_key": {"skill_name": "S"},
    "skill.inspect.load_runtime_failed": {"detail": "e"},
    "skill.inspect.sandbox_network_blocked": {"skill_name": "S"},
    "skill.inspect.skill_run_failed": {"detail": "e"},
    "skill.inspect.sandbox_crashed": {"detail": "e"},
    "skill.inspect.host_failed": {"detail": "e"},
}


def _load_common(locale: str) -> dict[str, str]:
    p = _LOCALES_DIR / locale / "common.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return {str(k): str(v) for k, v in data.items()}


@pytest.mark.parametrize("key", WAVE3_KEYS)
def test_wave3_keys_exist_en_zh(key: str) -> None:
    en = _load_common("en")
    zh = _load_common("zh-Hans")
    assert key in en and en[key].strip()
    assert key in zh and zh[key].strip()


@pytest.mark.parametrize("key,kwargs", list(_FORMAT_SAMPLES.items()))
def test_wave3_format_safe(key: str, kwargs: dict[str, str]) -> None:
    tr = default_translator()
    for loc in ("en", "zh-Hans"):
        tr.t(key, locale=loc, **kwargs)


def test_jinja_skill_debug_header_renders() -> None:
    from adami_kernel.i18n.jinja_render import render_i18n_template

    out = render_i18n_template(
        "skill_debug/failure_header.j2",
        skill_name="TEST",
        error_type="syntax",
        timestamp="20260101_120000",
        error_info="line 1\nline 2",
    )
    assert "TEST" in out
    assert "syntax" in out
    assert "line 1" in out
