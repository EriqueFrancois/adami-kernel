# -*- coding: utf-8 -*-
"""Wave 2: orchestrator / planner / HITL catalog keys (en + zh-Hans)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adami_kernel.i18n.catalog import default_translator

_LOCALES_DIR = Path(__file__).resolve().parents[1] / "src" / "adami_kernel" / "i18n" / "locales"

ORCH_PLANNER_KEYS: tuple[str, ...] = (
    "planner.skill_create.path_unavailable",
    "planner.skill_create.failed_with_detail",
    "planner.iteration.exec_failed",
    "planner.evaluator.remaining_fallback",
    "planner.task.incomplete",
    "planner.result.exec_error",
    "planner.result.unknown_error",
    "planner.result.task_failed",
    "planner.result.no_valid_result",
    "planner.result.exec_success",
    "planner.result.task_issue",
    "planner.skill_exec.failed",
    "planner.skillcomposer.workflow_failed",
    "planner.multi_agent.exec_failed",
    "planner.workflow_engine.started",
    "planner.workflow_engine.start_failed",
    "planner.plan.failed_no_steps",
    "planner.step.skill_tdd_solidified",
    "planner.step.skill_tdd_failed",
    "planner.step.step_failed",
    "planner.multi_agent.pause_ok",
    "planner.multi_agent.resume_ok",
    "planner.multi_agent.plan_not_found",
    "planner.monitor.degrade_note",
    "planner.error.workflow_not_ready",
    "planner.digest.body_truncated",
    "planner.pipe.iteration_abort_keywords",
    "planner.pipe.meeting_keywords",
    "planner.pipe.crypto_param_hints",
    "planner.pipe.skill_invoke_hints",
    "shared.pipe.common_cities_cn",
    "critic.pipe.weather_score_tokens",
    "critic.pipe.price_score_tokens",
    "critic.pipe.empty_score_markers",
    "critic.reject.data_empty",
    "critic.reject.weather_invalid",
    "critic.feedback.invalid_data",
    "critic.suggestion.check_weather_api",
    "critic.feedback.approved_ok",
    "critic.pipe.city_required_errors",
    "critic.feedback.exec_failed_city",
    "critic.suggestion.check_city_extraction",
    "critic.llm.section_execution",
    "critic.llm.review_prompt",
    "critic.feedback.json_parse_fail",
    "critic.feedback.validate_fail",
    "researcher.weather.summary_format",
    "researcher.error.no_search_results",
    "researcher.fallback.summary_done",
    "researcher.error.search_timeout",
    "orch.magent.error.no_start_node",
    "orch.magent.error.workflow_ended",
    "orch.magent.error.evolution_engine_missing",
    "orch.magent.error.skill_not_found",
    "orch.magent.error.router_missing",
    "orch.magent.error.invalid_condition",
    "orch.magent.error.condition_branch",
    "orch.magent.error.unsupported_node",
    "orch.pipe.skill_missing_tokens",
    "te.reason.weather_valid_data",
    "te.reason.weather_invalid_data",
    "te.reason.skill_data_ok",
    "te.remaining.weather_skill_with_city_hint",
    "te.cityhint.example_beijing",
    "te.remaining.weather_with_city",
    "te.remaining.city_required_short",
    "te.llm.context_header",
    "te.llm.evaluate_prompt",
    "te.reason.eval_fallback",
    "te.reason.eval_exception",
    "ir.msg.force_optimize_need_skill",
    "ir.prompt.fast_router",
    "ir.msg.received_ok",
    "ir.prompt.translate_strict",
    "ir.msg.translate_failed",
    "ir.prompt.self_intro",
    "ir.fallback.self_intro",
    "ir.prompt.short_answer",
    "ir.msg.checkmark_only",
    "orch.hitl.paused_message",
    "orch.hitl.btn_retry",
    "orch.hitl.btn_provide_extra",
    "orch.hitl.btn_cancel_task",
    "orch.hitl.reason_high_risk_node",
    "orch.hitl.reason_task_timeouts",
    "orch.hitl.reason_circuit_errors",
    "orch.human.default_reason",
    "orch.human.intervention_message",
    "orch.human.btn_continue",
    "orch.human.btn_pause",
    "orch.human.btn_provide",
    "wfe.error.deerflow_node_disabled",
    "wfe.error.deerflow_requires_flag",
    "wfe.error.max_steps",
    "wfe.msg.simple_node_passed",
    "wfe.error.router_missing",
    "wfe.error.evolution_missing",
    "wfe.error.skill_build_failed",
    "wfe.msg.skill_built_from_workflow",
    "wfe.error.skill_missing",
    "wfe.error.invalid_condition",
    "wfe.error.condition_no_next",
    "wfe.warn.condition_missing_true",
    "wfe.warn.condition_missing_false",
    "wfe.warn.condition_static_fallback",
    "wfe.warn.condition_single_branch",
    "wfe.warn.condition_terminal",
    "wfe.msg.node_done",
    "wfe.error.node_failed",
    "wfe.error.workflow_cancelled",
    "sc.compose.no_skills",
    "sc.node.desc.invoke_skill",
    "sc.node.prompt.handle_task",
    "sc.node.desc.llm",
    "sc.node.desc.llm_final",
    "sc.prompt.create_new_skill",
    "sc.node.prompt.research",
    "sc.node.desc.research",
    "sc.node.prompt.engineer",
    "sc.node.desc.engineer",
    "sc.node.desc.executor",
    "sc.node.prompt.critic",
    "sc.node.desc.critic",
    "sc.prompt.compose_workflow",
    "sc.prompt.compose_retry",
)

_FORMAT_SAMPLES: dict[str, dict[str, str]] = {
    "planner.skill_create.failed_with_detail": {"detail": "x"},
    "planner.iteration.exec_failed": {"detail": "e"},
    "planner.result.exec_error": {"detail": "e"},
    "planner.result.task_failed": {"detail": "e"},
    "planner.result.task_issue": {"detail": "e"},
    "planner.skill_exec.failed": {"detail": "e"},
    "planner.skillcomposer.workflow_failed": {"detail": "e"},
    "planner.multi_agent.exec_failed": {"detail": "e"},
    "planner.workflow_engine.started": {"workflow_id": "wf1"},
    "planner.workflow_engine.start_failed": {"detail": "e"},
    "planner.step.skill_tdd_solidified": {"skill_name": "SK"},
    "planner.step.skill_tdd_failed": {"reason": "r"},
    "planner.step.step_failed": {"detail": "e"},
    "planner.multi_agent.pause_ok": {"trace_id": "t1"},
    "planner.multi_agent.resume_ok": {"trace_id": "t1"},
    "orch.hitl.paused_message": {"reason": "deadlock"},
    "orch.hitl.reason_high_risk_node": {"node_id": "n1"},
    "orch.hitl.reason_task_timeouts": {"agent_role": "engineer"},
    "orch.hitl.reason_circuit_errors": {"error_type": "ValueError"},
    "orch.human.intervention_message": {"workflow_id": "wf1", "reason": "retry"},
    "critic.reject.weather_invalid": {"preview": "p"},
    "critic.feedback.invalid_data": {"reason": "r"},
    "critic.feedback.exec_failed_city": {"error_msg": "e"},
    "critic.llm.review_prompt": {
        "task_description": "td",
        "schema_json": "{}",
        "error_recall": "",
        "previous_result_json": "{}",
        "execution_section": "",
    },
    "critic.feedback.validate_fail": {"detail": "d"},
    "researcher.weather.summary_format": {"city": "Tokyo", "weather_data": "Sunny"},
    "researcher.error.search_timeout": {"query": "q"},
    "orch.magent.error.workflow_ended": {"status": "FAILED"},
    "orch.magent.error.skill_not_found": {"skill_name": "X"},
    "orch.magent.error.invalid_condition": {"condition_template": "$x == 1"},
    "orch.magent.error.unsupported_node": {"node_type": "FOO"},
    "te.remaining.weather_skill_with_city_hint": {"city_hint": "Beijing"},
    "te.remaining.weather_with_city": {"city": "Shanghai"},
    "te.llm.evaluate_prompt": {
        "original_task": "t",
        "current_result": "r",
        "context_block": "",
    },
    "te.reason.eval_exception": {"detail": "d"},
    "ir.prompt.fast_router": {"task": "hi"},
    "ir.prompt.translate_strict": {"text_to_translate": "hello"},
    "ir.msg.translate_failed": {"text": "x"},
    "ir.prompt.short_answer": {"task": "q"},
    "wfe.error.deerflow_node_disabled": {"node_id": "n1"},
    "wfe.error.max_steps": {"max_steps": "99"},
    "wfe.msg.simple_node_passed": {"node_type": "LLM_CALL"},
    "wfe.error.skill_build_failed": {"detail": "d"},
    "wfe.msg.skill_built_from_workflow": {"skill_name": "sk"},
    "wfe.error.skill_missing": {"skill_name": "sk"},
    "wfe.error.invalid_condition": {"condition_template": "$x == 1"},
    "wfe.warn.condition_missing_true": {"node_id": "n4", "fallback": "n5"},
    "wfe.warn.condition_missing_false": {"node_id": "n4", "fallback": "n3"},
    "wfe.warn.condition_static_fallback": {"node_id": "n4", "nxt": "n5"},
    "wfe.warn.condition_single_branch": {"node_id": "n4", "nxt": "n5"},
    "wfe.warn.condition_terminal": {"node_id": "n4"},
    "wfe.msg.node_done": {"node_id": "n1"},
    "wfe.error.node_failed": {"node_id": "n1", "detail": "d"},
    "wfe.error.workflow_cancelled": {"workflow_id": "wf1"},
    "sc.node.desc.invoke_skill": {"skill_name": "sk"},
    "sc.node.prompt.handle_task": {"task_description": "td"},
    "sc.prompt.create_new_skill": {"task_description": "td"},
    "sc.prompt.compose_workflow": {"task_description": "td", "skills_block": "a, b"},
    "sc.prompt.compose_retry": {"task_description": "td", "skills_block": "a"},
}


def _load_common(locale: str) -> dict[str, str]:
    p = _LOCALES_DIR / locale / "common.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return {str(k): str(v) for k, v in data.items()}


@pytest.mark.parametrize("key", ORCH_PLANNER_KEYS)
def test_orch_planner_keys_exist_en_zh(key: str) -> None:
    en = _load_common("en")
    zh = _load_common("zh-Hans")
    assert key in en and en[key].strip()
    assert key in zh and zh[key].strip()


@pytest.mark.parametrize("key,kwargs", list(_FORMAT_SAMPLES.items()))
def test_orch_planner_format_safe(key: str, kwargs: dict[str, str]) -> None:
    tr = default_translator()
    for loc in ("en", "zh-Hans"):
        tr.t(key, locale=loc, **kwargs)


def test_sample_bilingual_diff() -> None:
    tr = default_translator()
    k = "orch.human.intervention_message"
    a = tr.t(k, locale="en", workflow_id="w", reason="r")
    b = tr.t(k, locale="zh-Hans", workflow_id="w", reason="r")
    assert a != b
