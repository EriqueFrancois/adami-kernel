from __future__ import annotations

import json
from pathlib import Path

import pytest

from adami_kernel.config import Settings, cli_overrides_env_path
from adami_kernel.i18n.catalog import t
from adami_kernel.i18n.keys import UI
from adami_kernel.i18n.locale_resolve import resolve_effective_locale
from adami_kernel.i18n.request_locale import attach_request_locale, reset_request_locale


def test_resolve_locale_order_chat_payload_brain_default() -> None:
    sup = ["en", "zh-Hans"]
    payload = {"locale": "zh_CN"}
    assert (
        resolve_effective_locale(
            payload=payload,
            chat_id="c1",
            chat_overrides={"c1": "en"},
            brain_root=None,
            brain_locale_rel="System/working-memory/locale.json",
            default_locale="zh-Hans",
            supported_locales=sup,
        )
        == "en"
    )
    assert (
        resolve_effective_locale(
            payload=payload,
            chat_id="c2",
            chat_overrides={},
            brain_root=None,
            brain_locale_rel="System/working-memory/locale.json",
            default_locale="en",
            supported_locales=sup,
        )
        == "zh-Hans"
    )


def test_resolve_locale_brain_file(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    rel = Path("System/working-memory/locale.json")
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"locale": "zh_CN"}, ensure_ascii=False), encoding="utf-8")
    sup = ["en", "zh-Hans"]
    assert (
        resolve_effective_locale(
            payload={},
            chat_id="x",
            chat_overrides={},
            brain_root=root,
            brain_locale_rel=str(rel).replace("\\", "/"),
            default_locale="en",
            supported_locales=sup,
        )
        == "zh-Hans"
    )


def test_t_changes_with_request_locale_context() -> None:
    en_line = t(UI.MENU_ENTRY, locale="en")
    tok = attach_request_locale("zh-Hans")
    try:
        zh_line = t(UI.MENU_ENTRY)
    finally:
        reset_request_locale(tok)
    assert "Normal chat" in en_line
    assert "正常对话" in zh_line
    assert en_line != zh_line


def test_settings_invalid_default_locale_normalized_to_supported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADAMI_DEFAULT_LOCALE", "xx-YY")
    monkeypatch.setenv("ADAMI_SUPPORTED_LOCALES", '["en","zh-Hans"]')
    s = Settings(_env_file=())
    assert s.ADAMI_DEFAULT_LOCALE == "en"


def test_cli_overrides_env_path_respects_adami_data_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("ADAMI_CLI_ENV_FILE", raising=False)
    d = tmp_path / "data"
    monkeypatch.setenv("ADAMI_DATA_DIR", str(d))
    assert cli_overrides_env_path() == d / "cli_overrides.env"
