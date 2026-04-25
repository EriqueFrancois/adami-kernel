"""Telegram/Discord 交互式系统设置向导（与 CLI 同一套 Settings 覆盖层）。

目标：
- 首次进入「系统设置」后，按“分类 → 字段 → 输入值”三段式引导修改 config 中的选项
- 覆盖写入 `.adami_data/cli_overrides.env`（或 ADAMI_CLI_ENV_FILE 指定路径）
- 不通过关键词匹配触发；仅当用户明确选择进入设置后才消费输入
"""

from __future__ import annotations

import dataclasses
from typing import Any, Dict, List, Optional, Tuple

from adami_kernel.config import Settings, reload_settings
from adami_kernel.nexus.cli_settings_wizard import (
    _CATEGORIES,
    _coerce_value,
    _display_value,
    _fields_by_category,
    _format_stored_value,
    _is_secret_field,
    mcp_servers_json_template,
    write_cli_overrides,
)

LANGUAGE_CATEGORY_ID = "language"


def _language_category_index() -> int:
    for i, (cid, _) in enumerate(_CATEGORIES):
        if cid == LANGUAGE_CATEGORY_ID:
            return i + 1
    return -1


def _t(key: str, **kwargs: Any) -> str:
    from adami_kernel.config import settings
    from adami_kernel.i18n import t

    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


@dataclasses.dataclass
class ChatSettingsState:
    stage: str = "category"  # category | field | value | language_menu
    category_id: Optional[str] = None
    field_name: Optional[str] = None
    # 当从「系统设置」进入简报向导时，由 handle_text 置位；外层 nerve 读取后启动 report UI
    start_report_wizard: bool = False
    exit_to_main: bool = False


def menu_text() -> str:
    reload_settings()
    return _t("settings.menu.entry")


def categories_text() -> str:
    reload_settings()
    by = _fields_by_category()
    lines = [_t("settings.categories.title"), ""]
    for i, (cid, title_key) in enumerate(_CATEGORIES, start=1):
        n = len(by.get(cid, []))
        lines.append(_t("settings.categories.item", idx=i, title=_t(title_key), count=n))
    nxt = len(_CATEGORIES) + 1
    lines.append(_t("settings.categories.report_row", n=nxt))
    lines.append("")
    lines.append(_t("settings.categories.footer"))
    return "\n".join(lines)


def language_quick_pick_text() -> str:
    reload_settings()
    lines = [
        _t("settings.language.quick_title"),
        "",
        f"1. {_t('settings.language.option_en')}",
        f"2. {_t('settings.language.option_zh')}",
        "",
        _t("settings.language.pick_hint"),
        "",
        _t("settings.categories.footer"),
    ]
    return "\n".join(lines)


def entry_menu_telegram_buttons() -> List[Dict[str, str]]:
    reload_settings()
    return [
        {"text": _t("settings.entry.btn_normal"), "callback_data": "menu:normal"},
        {"text": _t("settings.entry.btn_settings"), "callback_data": "menu:settings"},
        {"text": _t("settings.entry.btn_restart"), "callback_data": "menu:restart"},
        {"text": _t("settings.entry.btn_report"), "callback_data": "menu:report"},
    ]


def entry_menu_discord_button_labels() -> tuple[str, str, str, str]:
    reload_settings()
    a = _t("settings.entry.btn_normal")
    b = _t("settings.entry.btn_settings")
    c = _t("settings.entry.btn_restart")
    d = _t("settings.entry.btn_report")
    return (a[:80], b[:80], c[:80], d[:80])


def closed_settings_ack_text() -> str:
    reload_settings()
    return _t("settings.closed_settings")


def fields_text(category_id: str) -> str:
    by = _fields_by_category()
    names = by.get(category_id, [])
    title_key = next((k for cid, k in _CATEGORIES if cid == category_id), "settings.category.other")
    title = _t(title_key)
    s = reload_settings()
    lines = [
        _t(
            "settings.field_list.header",
            title=title,
            subtitle=_t("settings.field_list.subtitle"),
        ),
        "",
    ]
    for i, name in enumerate(names, start=1):
        lines.append(f"{i}. {name} = {_display_value(name, getattr(s, name))}")
    lines.append("")
    lines.append(_t("settings.categories.footer"))
    return "\n".join(lines)


def field_prompt(field_name: str) -> str:
    info = Settings.model_fields[field_name]
    s = reload_settings()
    cur = getattr(s, field_name)
    lines = [
        _t("settings.field_prompt.label_field", field_name=field_name),
        _t("settings.field_prompt.label_type", type_str=str(info.annotation)),
        _t(
            "settings.field_prompt.label_current",
            current=_display_value(field_name, cur),
        ),
    ]
    if _is_secret_field(field_name):
        lines.append(_t("settings.field_prompt.secret_warning"))
    lines.append("")
    if field_name == "ADAMI_MCP_SERVERS_JSON":
        lines.append(_t("settings.field_prompt.mcp_json_paste_hint"))
    if field_name == "ADAMI_UI_LOCALE":
        lines.append(_t("settings.field_prompt.ui_locale_hint"))
    lines.append(_t("settings.field_prompt.instruction"))
    return "\n".join(lines)


def handle_text(
    state: ChatSettingsState, text: str
) -> Tuple[ChatSettingsState, str, Optional[List[Dict[str, str]]]]:
    """处理用户在「系统设置」中的输入。返回：新 state、回复文本、可选按钮（通用结构）。"""
    t = (text or "").strip()
    if not t:
        return state, _t("settings.reply.empty"), None
    if t.lower() == "r":
        reload_settings()
        if state.stage == "category":
            return state, categories_text(), None
        if state.stage == "language_menu":
            return state, language_quick_pick_text(), None
        if state.stage == "field" and state.category_id:
            return state, fields_text(state.category_id), None
        if state.stage == "value" and state.field_name:
            return state, field_prompt(state.field_name), None
        return ChatSettingsState(), categories_text(), None

    if t == "0":
        if state.stage == "language_menu":
            return ChatSettingsState(stage="category"), categories_text(), None
        if state.stage == "category":
            return (
                ChatSettingsState(stage="category", exit_to_main=True),
                _t("settings.exit_to_main_reply"),
                None,
            )
        if state.stage == "field":
            return ChatSettingsState(stage="category"), categories_text(), None
        if state.stage == "value" and state.category_id:
            return (
                ChatSettingsState(stage="field", category_id=state.category_id),
                fields_text(state.category_id),
                None,
            )
        return ChatSettingsState(stage="category"), categories_text(), None

    if state.stage == "language_menu":
        try:
            choice = int(t)
        except ValueError:
            return (
                state,
                _t("settings.language.invalid") + "\n\n" + language_quick_pick_text(),
                None,
            )
        if choice not in (1, 2):
            return (
                state,
                _t("settings.language.invalid") + "\n\n" + language_quick_pick_text(),
                None,
            )
        loc_val = "en" if choice == 1 else "zh-Hans"
        write_cli_overrides({"ADAMI_UI_LOCALE": loc_val})
        reload_settings()
        return (
            ChatSettingsState(stage="category"),
            _t("settings.language.saved") + "\n\n" + categories_text(),
            None,
        )

    if state.stage == "value" and t.lower() == "clear" and state.field_name:
        write_cli_overrides({state.field_name: None})
        reload_settings()
        return (
            ChatSettingsState(stage="field", category_id=state.category_id),
            _t(
                "settings.field_prompt.override_cleared",
                field_name=state.field_name,
                fields_block=fields_text(state.category_id or ""),
            ),
            None,
        )

    if (
        state.stage == "value"
        and state.field_name == "ADAMI_MCP_SERVERS_JSON"
        and t.lower() == "tpl"
    ):
        tpl = mcp_servers_json_template()
        return state, _t("settings.field_prompt.mcp_json_template_header", tpl=tpl), None

    if state.stage == "category":
        try:
            idx = int(t)
        except ValueError:
            return state, _t("settings.reply.bad_category"), None
        if idx == len(_CATEGORIES) + 1:
            return (
                ChatSettingsState(stage="category", start_report_wizard=True),
                _t("settings.report_wizard_opening"),
                None,
            )
        if idx < 1 or idx > len(_CATEGORIES):
            return state, _t("settings.reply.invalid_number"), None
        if idx == _language_category_index():
            return ChatSettingsState(stage="language_menu"), language_quick_pick_text(), None
        cid, _title = _CATEGORIES[idx - 1]
        return ChatSettingsState(stage="field", category_id=cid), fields_text(cid), None

    if state.stage == "field":
        if not state.category_id:
            return ChatSettingsState(), categories_text(), None
        names = _fields_by_category().get(state.category_id, [])
        try:
            idx = int(t)
        except ValueError:
            return state, _t("settings.reply.bad_field"), None
        if idx < 1 or idx > len(names):
            return state, _t("settings.reply.invalid_number"), None
        fname = names[idx - 1]
        return (
            ChatSettingsState(stage="value", category_id=state.category_id, field_name=fname),
            field_prompt(fname),
            None,
        )

    if state.stage == "value" and state.field_name:
        info = Settings.model_fields[state.field_name]
        try:
            parsed = _coerce_value(state.field_name, info.annotation, t)
        except ValueError as e:
            return (
                state,
                _t(
                    "settings.field_prompt.coerce_error",
                    detail=str(e),
                    prompt_block=field_prompt(state.field_name),
                ),
                None,
            )
        stored = _format_stored_value(parsed)
        write_cli_overrides({state.field_name: stored})
        reload_settings()
        return (
            ChatSettingsState(stage="field", category_id=state.category_id),
            _t(
                "settings.field_prompt.saved_ok",
                field_name=state.field_name,
                fields_block=fields_text(state.category_id or ""),
            ),
            None,
        )

    return ChatSettingsState(), categories_text(), None
