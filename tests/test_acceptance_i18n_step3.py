"""
模块六 — 步骤 3 验收（系统设置向导：语言切换）

验收范围：
1. CLI 向导分类含「语言 / Language」「模块五：last30days」；语言类含 ADAMI_DEFAULT_LOCALE、ADAMI_SYSTEM_UI_LOCALE、ADAMI_SUPPORTED_LOCALES、ADAMI_UI_LOCALE。
2. 聊天向导：选择语言分类后进入数字快选（1=en，2=zh-Hans），写入 ADAMI_UI_LOCALE + reload_settings（与现有 overrides 模式一致）。
3. 入口菜单 / 分类列表等向导文案随 effective_ui_default_locale() 切换（menu_text、categories_text）。
4. 返回主菜单：exit_to_main 标志 + 关闭提示文案走 i18n。
5. /report help 走 catalog 键 report.help.body（在 DecisionProcessor 请求上下文中随语言变化；本文件用静态 t 抽查键存在与转义安全）。

建议执行：
``pytest tests/test_acceptance_i18n_step3.py tests/test_chat_settings_language.py -q``
回归：``pytest -m "not integration" -q``
"""

from __future__ import annotations

from pathlib import Path

import pytest

from adami_kernel.config import Settings, reload_settings
from adami_kernel.i18n import t
from adami_kernel.i18n.locale_utils import normalize_locale
from adami_kernel.nexus import chat_settings_wizard as csw
from adami_kernel.nexus.cli_settings_wizard import (
    _CATEGORIES,
    _fields_by_category,
    write_cli_overrides,
)


def test_step3_language_category_in_cli_wizard() -> None:
    ids = [cid for cid, _ in _CATEGORIES]
    assert "language" in ids
    assert "last30days" in ids
    titles = [t for cid, t in _CATEGORIES if cid == "language"]
    assert titles and ("语言" in titles[0] or "Language" in titles[0])


def test_step3_language_fields_in_category() -> None:
    by = _fields_by_category()
    lang = by.get("language", [])
    for name in (
        "ADAMI_DEFAULT_LOCALE",
        "ADAMI_SUPPORTED_LOCALES",
        "ADAMI_UI_LOCALE",
        "ADAMI_SYSTEM_UI_LOCALE",
    ):
        assert name in lang, f"missing {name} in language category"
    l30 = by.get("last30days", [])
    assert "ADAMI_LAST30DAYS_ENABLED" in l30


def test_step3_menu_and_categories_follow_ui_locale(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ADAMI_DATA_DIR", str(tmp_path))
    write_cli_overrides({"ADAMI_UI_LOCALE": "en"})
    reload_settings()
    mt_en = csw.menu_text()
    assert "Normal" in mt_en
    assert "settings" in mt_en.lower() or "Settings" in mt_en

    write_cli_overrides({"ADAMI_UI_LOCALE": "zh-Hans"})
    reload_settings()
    assert "正常对话" in csw.menu_text()
    cat_zh = csw.categories_text()
    assert "系统设置" in cat_zh or "分类" in cat_zh

    write_cli_overrides({"ADAMI_UI_LOCALE": None})
    reload_settings()


def test_step3_report_help_catalog_has_body() -> None:
    body_en = t("report.help.body", locale="en")
    assert "report:wizard" in body_en.lower()
    assert "telegram" in body_en.lower()
    body_zh = t("report.help.body", locale="zh-Hans")
    assert "向导" in body_zh or "report:wizard" in body_zh.lower()


def test_step3_effective_ui_falls_back_to_system_ui_when_ui_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ADAMI_UI_LOCALE", raising=False)

    s = Settings(_env_file=())
    assert s.ADAMI_UI_LOCALE is None or str(s.ADAMI_UI_LOCALE).strip() == ""
    assert s.ADAMI_DEFAULT_LOCALE == "en"
    assert s.effective_ui_default_locale() == normalize_locale(str(s.ADAMI_SYSTEM_UI_LOCALE))
