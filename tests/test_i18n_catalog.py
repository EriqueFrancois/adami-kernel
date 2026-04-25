from __future__ import annotations

import json
from pathlib import Path

import pytest

from adami_kernel.i18n.catalog import Translator, normalize_locale
from adami_kernel.i18n.keys import UI


def test_normalize_locale_zh_aliases() -> None:
    assert normalize_locale("zh_CN") == "zh-Hans"
    assert normalize_locale("zh-CN") == "zh-Hans"
    assert normalize_locale("  EN  ") == "en"


def test_fallback_missing_key_warns_only_in_dev_mode(caplog: pytest.LogCaptureFixture) -> None:
    tr = Translator(default_locale="zh-Hans", dev_warn_missing=True)
    with caplog.at_level("WARNING"):
        s = tr.t("this.key.does.not.exist")
    assert s == "this.key.does.not.exist"
    assert "missing key" in caplog.text


def test_fallback_zh_to_en() -> None:
    tr = Translator(default_locale="zh-Hans")
    assert tr.t(UI.MENU_ENTRY).startswith("1")


def test_override_dir_merges(tmp_path: Path) -> None:
    ov = tmp_path / "overrides"
    ov.mkdir(parents=True, exist_ok=True)
    (ov / "en.json").write_text(
        json.dumps({"ui.menu.entry": "OVERRIDDEN"}, ensure_ascii=False),
        encoding="utf-8",
    )
    tr = Translator(default_locale="en")
    tr.set_override_dir(str(ov))
    assert tr.t(UI.MENU_ENTRY) == "OVERRIDDEN"


def test_memory_override_wins(tmp_path: Path) -> None:
    ov = tmp_path / "overrides"
    ov.mkdir(parents=True, exist_ok=True)
    (ov / "en.json").write_text(
        json.dumps({"ui.menu.entry": "DISK"}, ensure_ascii=False),
        encoding="utf-8",
    )
    tr = Translator(default_locale="en")
    tr.set_override_dir(str(ov))
    tr.set_memory_override("en", {"ui.menu.entry": "MEM"})
    assert tr.t(UI.MENU_ENTRY) == "MEM"


def test_format_missing_placeholder_raises() -> None:
    tr = Translator(default_locale="en")
    with pytest.raises(ValueError) as ei:
        tr.t("errors.report.json_invalid")
    assert "missing placeholder" in str(ei.value)


def test_format_with_kwargs() -> None:
    tr = Translator(default_locale="en")
    assert "oops" in tr.t("errors.report.json_invalid", detail="oops")


def test_json_literal_catalog_keys_format_without_kwargs() -> None:
    """Catalog values that embed JSON must use {{ }} so str.format does not eat braces."""
    tr_en = Translator(default_locale="en")
    tr_zh = Translator(default_locale="zh-Hans")
    ex = tr_en.t("dp.intake.prompt_example_json")
    assert ex.strip().startswith("{") and '"domain"' in ex
    assert tr_zh.t("dp.intake.prompt_example_json").strip().startswith("{")
    raw = tr_en.t("sfac.name.map_json")
    m = json.loads(raw)
    assert m["查询"] == "QUERY"
    assert json.loads(tr_zh.t("sfac.name.map_json")) == m
