"""
模块六 — 步骤 2 验收（语言偏好：配置 + 运行时状态）

验收范围（与实现一致）：
1. Settings：ADAMI_DEFAULT_LOCALE 默认为 en；支持列表含 en/zh-Hans；非法默认回退到支持集。
2. 数据路径：chat 级覆盖文件位于 ADAMI_DATA_DIR 下 chat_locale_overrides.json（由 path_chat_locale_overrides_json 暴露）。
3. CLI 覆盖层：未设 ADAMI_CLI_ENV_FILE 且已设 ADAMI_DATA_DIR 时，cli_overrides 与数据目录对齐。
4. 解析链：chat 持久化 > payload > SecondBrain locale.json > 默认 > en。
5. 请求内 i18n：DecisionProcessor 同路径依赖 contextvars；t() 在 attach_request_locale 下随语言变化。
6. 文档种子：SecondBrain 初始化包含 System/working-memory/locale.json（由 SecondBrainManager.initialize 保证）。

执行：``pytest tests/test_acceptance_i18n_step2.py tests/test_locale_resolution.py -q``
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adami_kernel.config import Settings, cli_overrides_env_path, settings
from adami_kernel.hippocampus.second_brain import SecondBrainManager
from adami_kernel.i18n.catalog import default_translator, t
from adami_kernel.i18n.keys import UI
from adami_kernel.i18n.locale_resolve import resolve_effective_locale, save_chat_locale_map
from adami_kernel.i18n.request_locale import attach_request_locale, reset_request_locale


def test_step2_settings_model_declares_i18n_fields() -> None:
    names = Settings.model_fields
    assert "ADAMI_DEFAULT_LOCALE" in names
    assert "ADAMI_SYSTEM_UI_LOCALE" in names
    assert "ADAMI_SUPPORTED_LOCALES" in names
    assert "ADAMI_BRAIN_LOCALE_JSON_RELATIVE" in names
    fi = names["ADAMI_DEFAULT_LOCALE"]
    assert fi.default == "en"
    assert names["ADAMI_SYSTEM_UI_LOCALE"].default == "zh-Hans"


def test_step2_fresh_settings_default_locale_en_when_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("ADAMI_DEFAULT_LOCALE", raising=False)
    monkeypatch.delenv("ADAMI_SUPPORTED_LOCALES", raising=False)
    s = Settings(_env_file=())
    assert s.ADAMI_DEFAULT_LOCALE == "en"
    assert "en" in s.ADAMI_SUPPORTED_LOCALES
    assert "zh-Hans" in s.ADAMI_SUPPORTED_LOCALES
    assert s.ADAMI_BRAIN_LOCALE_JSON_RELATIVE == "System/working-memory/locale.json"


def test_step2_default_translator_follows_settings_default() -> None:
    assert default_translator().default_locale == settings.effective_ui_default_locale()


def test_step2_path_chat_locale_overrides_under_data_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ADAMI_DATA_DIR", str(tmp_path / "d"))
    s = Settings(_env_file=())
    assert s.path_chat_locale_overrides_json == str(
        (tmp_path / "d").resolve() / "chat_locale_overrides.json"
    )


def test_step2_cli_overrides_path_when_data_dir_set(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("ADAMI_CLI_ENV_FILE", raising=False)
    d = tmp_path / "data"
    monkeypatch.setenv("ADAMI_DATA_DIR", str(d))
    assert cli_overrides_env_path() == d / "cli_overrides.env"


def test_step2_resolve_chain_and_t_under_context() -> None:
    sup = ["en", "zh-Hans"]
    assert (
        resolve_effective_locale(
            payload={"locale": "zh-Hans"},
            chat_id="k",
            chat_overrides={"k": "en"},
            brain_root=None,
            brain_locale_rel="System/working-memory/locale.json",
            default_locale="zh-Hans",
            supported_locales=sup,
        )
        == "en"
    )
    tok = attach_request_locale("zh-Hans")
    try:
        assert "正常对话" in t(UI.MENU_ENTRY)
    finally:
        reset_request_locale(tok)


def test_step2_second_brain_seeds_locale_json(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    mgr = SecondBrainManager(root_dir=str(root))
    import asyncio

    asyncio.run(mgr.initialize())
    p = root / "System" / "working-memory" / "locale.json"
    assert p.is_file()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert "locale" in data


def test_step2_chat_locale_map_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "chat_locale_overrides.json"
    save_chat_locale_map(p, {"room-1": "zh-Hans"})
    body = json.loads(p.read_text(encoding="utf-8"))
    assert body["room-1"] == "zh-Hans"


def test_step2_env_example_documents_locale_vars() -> None:
    root = Path(__file__).resolve().parents[1]
    ex = (root / ".env.example").read_text(encoding="utf-8")
    assert "ADAMI_DEFAULT_LOCALE" in ex
    assert "ADAMI_SYSTEM_UI_LOCALE" in ex
    assert "ADAMI_SUPPORTED_LOCALES" in ex
