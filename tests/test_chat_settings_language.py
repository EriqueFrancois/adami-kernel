"""Chat settings wizard: language category quick-pick + UI locale."""

from __future__ import annotations

import pytest

from adami_kernel.config import Settings, _settings_env_files
from adami_kernel.nexus import chat_settings_wizard as csw
from adami_kernel.nexus.cli_settings_wizard import _CATEGORIES, _fields_by_category


def test_language_category_exists() -> None:
    ids = [cid for cid, _ in _CATEGORIES]
    assert "language" in ids


def test_language_fields_grouped() -> None:
    by = _fields_by_category()
    lang = by.get("language", [])
    assert "ADAMI_DEFAULT_LOCALE" in lang
    assert "ADAMI_UI_LOCALE" in lang
    assert "ADAMI_SYSTEM_UI_LOCALE" in lang
    assert "ADAMI_SUPPORTED_LOCALES" in lang


def test_language_quick_pick_writes_ui_locale(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("ADAMI_DATA_DIR", str(tmp_path))
    st = csw.ChatSettingsState(stage="language_menu")
    st2, reply, _ = csw.handle_text(st, "1")
    assert st2.stage == "category"
    assert "ADAMI_UI_LOCALE" in reply or "en" in reply.lower()
    s = Settings(_env_file=_settings_env_files(), _env_file_encoding="utf-8")
    assert s.ADAMI_UI_LOCALE == "en"


def test_language_quick_pick_zh(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("ADAMI_DATA_DIR", str(tmp_path))
    st = csw.ChatSettingsState(stage="language_menu")
    st2, reply, _ = csw.handle_text(st, "2")
    assert st2.stage == "category"
    s = Settings(_env_file=_settings_env_files(), _env_file_encoding="utf-8")
    assert s.ADAMI_UI_LOCALE == "zh-Hans"


def test_exit_to_main_flag(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setenv("ADAMI_DATA_DIR", str(tmp_path))
    st = csw.ChatSettingsState(stage="category")
    st2, reply, _ = csw.handle_text(st, "0")
    assert st2.exit_to_main is True
    assert "主菜单" in reply or "main menu" in reply.lower()
