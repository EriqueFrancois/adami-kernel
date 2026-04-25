# -*- coding: utf-8 -*-
"""Step 4 端口输出国际化 — 验收测试（自动化）

验收方案（概要）
================

1. **目录完整性**：Step 4 在代码中引用的 `port.*` / `shell.*` / `dp.*` 键在
   `locales/en/common.json` 与 `locales/zh-Hans/common.json` 中均存在且为非空字符串。

2. **占位符安全**：含 `{placeholder}` 的模板在提供全部占位参数时可通过
   `str.format` 渲染，不出现 `KeyError`（含 `{{` / `}}` 转义用法如 `dp.report.usage_set`）。

3. **双语差异**：抽样键在 en 与 zh-Hans 下渲染结果不同，避免误指向同一语言文件。

4. **回归**：与 Step 4 相关的单元/集成边界测试仍通过（本文件 + report wizard +
   report CLI + 既有 i18n step3）。

5. **协议未变**：Report 向导按钮的 `callback_data` 仍由既有测试覆盖（如
   `report:type:daily`），本验收不重复断言协议，仅保证文案键存在。

执行：`poetry run pytest tests/test_acceptance_i18n_step4_port_output.py -v`
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adami_kernel.i18n.catalog import default_translator

_LOCALES_DIR = Path(__file__).resolve().parents[1] / "src" / "adami_kernel" / "i18n" / "locales"

# 与 Step 4 实现保持一致的键集合（遗漏会在 CI 中失败）
STEP4_KEYS: tuple[str, ...] = (
    "port.boot.system_ready",
    "port.boot.settings_hint_after_menu",
    "port.thinking.multimodal",
    "port.media.unsupported",
    "port.callback.normal_answer",
    "port.callback.normal_message",
    "port.callback.settings_answer",
    "port.callback.close_answer",
    "port.callback.close_message",
    "port.digest.approved_message",
    "port.digest.rejected_message",
    "port.report.wizard_toast",
    "port.report.wizard_intro",
    "port.report.btn_daily",
    "port.report.btn_weekly",
    "port.report.btn_monthly",
    "port.report.btn_cancel",
    "port.report.cancel_toast",
    "port.report.cancel_message",
    "port.report.type_selected_toast",
    "port.report.sections_intro",
    "port.report.sec_general_news",
    "port.report.sec_sports",
    "port.report.sec_politics",
    "port.report.sec_military",
    "port.report.sec_tech_news",
    "port.report.btn_next_schedule",
    "port.report.toggle_updated_toast",
    "port.report.schedule_prompt_toast",
    "port.report.schedule_body_telegram",
    "port.report.schedule_body_discord",
    "port.report.schedule_bad_format",
    "port.report.schedule_submitted",
    "port.report.discord_started_ephemeral",
    "port.report.discord_type_selected_ephemeral",
    "port.report.discord_toggle_updated_ephemeral",
    "port.report.discord_submit_failed",
    "port.hitl.operation_received_toast",
    "port.hitl.workflow_action_message",
    "port.menu.close_settings_btn",
    "shell.menu.enter_prompt",
    "shell.menu.system_settings",
    "shell.menu.exit",
    "shell.prompt.choose",
    "shell.exit.goodbye",
    "shell.settings.interrupted",
    "shell.choice.invalid",
    "shell.prompt.hint_main",
    "shell.prompt.line",
    "shell.prompt.hint_interrupt",
    "shell.prompt.back_to_menu",
    "shell.cli_error",
    "dp.report.list_title",
    "dp.report.usage_show",
    "dp.report.err_bad_type",
    "dp.report.usage_set",
    "dp.report.json_parse_failed",
    "dp.report.updated",
    "dp.report.usage_run",
    "dp.report.disabled",
    "dp.report.push_header",
    "dp.report.generated_path",
    "dp.report.unknown_subcmd",
    "dp.session.busy",
    "dp.task.completed",
    "dp.circuit.user",
)

# 键 -> format 测试用 kwargs（仅用于含占位符的模板）
_FORMAT_SAMPLES: dict[str, dict[str, str]] = {
    "port.media.unsupported": {"ctype": "sticker"},
    "port.report.type_selected_toast": {"rtype": "daily"},
    "port.report.sections_intro": {"rtype": "weekly"},
    "port.report.schedule_submitted": {"rtype": "daily", "tz": "UTC", "hhmm": "09:00"},
    "port.report.discord_submit_failed": {"detail": "network"},
    "port.hitl.workflow_action_message": {"workflow_id": "wf1", "action": "approve"},
    "shell.cli_error": {"error": "EOF"},
    "dp.report.json_parse_failed": {"detail": "bad"},
    "dp.report.updated": {"rtype": "daily", "tz": "UTC", "time": "08:00"},
    "dp.report.disabled": {"rtype": "daily"},
    "dp.report.push_header": {"rtype": "Daily"},
    "dp.report.generated_path": {"path": "/tmp/x.md"},
    "dp.report.unknown_subcmd": {"cmd": "foo"},
    "dp.circuit.user": {"trace_id": "trace-1"},
}


def _load_common(locale: str) -> dict[str, str]:
    p = _LOCALES_DIR / locale / "common.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return {str(k): str(v) for k, v in data.items()}


@pytest.mark.parametrize("key", STEP4_KEYS)
def test_step4_key_present_in_en_and_zh(key: str) -> None:
    en = _load_common("en")
    zh = _load_common("zh-Hans")
    assert key in en, f"missing en: {key}"
    assert key in zh, f"missing zh-Hans: {key}"
    assert en[key].strip(), f"empty en: {key}"
    assert zh[key].strip(), f"empty zh-Hans: {key}"


def test_step4_bilingual_sample_differs() -> None:
    tr = default_translator()
    a = tr.t("port.boot.system_ready", locale="en")
    b = tr.t("port.boot.system_ready", locale="zh-Hans")
    assert a != b
    assert any("\u4e00" <= ch <= "\u9fff" for ch in b), "zh-Hans 启动文案应含汉字"


def test_step4_format_templates_render() -> None:
    tr = default_translator()
    for key, kwargs in _FORMAT_SAMPLES.items():
        out_en = tr.t(key, locale="en", **kwargs)
        out_zh = tr.t(key, locale="zh-Hans", **kwargs)
        assert out_en.strip(), key
        assert out_zh.strip(), key
        assert out_en != out_zh, f"{key}: en/zh should differ"


def test_step4_usage_set_escapes_json_braces() -> None:
    """dp.report.usage_set 使用 {{JSON}}，format 后用户可见字面量含 {JSON}。"""
    tr = default_translator()
    rendered = tr.t("dp.report.usage_set", locale="en")
    assert "JSON" in rendered
    assert "{{" not in rendered
    assert "/report set" in rendered


def test_report_wizard_buttons_protocol_unchanged() -> None:
    from adami_kernel.nexus.report_wizard_i18n import report_type_buttons

    rows = report_type_buttons()
    cds = [b["callback_data"] for b in rows]
    assert cds == [
        "report:type:daily",
        "report:type:weekly",
        "report:type:monthly",
        "report:cancel",
    ]
    assert all(b.get("text") for b in rows)


def test_report_section_toggle_callbacks_unchanged() -> None:
    from adami_kernel.nexus.report_wizard_i18n import report_section_toggle_buttons

    sec = {
        "general_news": True,
        "sports": False,
        "politics": False,
        "military": False,
        "tech_news": False,
    }
    rows = report_section_toggle_buttons(sec)
    expected_cds = [
        "report:toggle:general_news",
        "report:toggle:sports",
        "report:toggle:politics",
        "report:toggle:military",
        "report:toggle:tech_news",
        "report:next_schedule",
        "report:cancel",
    ]
    assert [b["callback_data"] for b in rows] == expected_cds
