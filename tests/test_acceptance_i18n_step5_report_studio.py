# -*- coding: utf-8 -*-
"""Step 5 Report Studio 国际化 — 验收测试（自动化）

验收方案（概要）
================

1. **目录完整性**：`report.studio.*` 键在 `locales/en/common.json` 与 `locales/zh-Hans/common.json`
   中均存在且非空；`title` 模板 `{kind}` 在 en/zh 下可正确 format。

2. **包内模板文件**：`src/adami_kernel/i18n/locales/en/report.md.j2` 与
   `zh-Hans/report.md.j2` 存在，且包含 Jinja 占位 `{{ labels.`（与渲染器契约一致）。

3. **标题本地化**：`localized_report_title(daily|weekly|monthly, locale)` 在两种语言下
   输出不同且符合 `report.studio.title` / `kind_*` 语义。

4. **配置**：`effective_report_locale()` 在仅设 `ADAMI_REPORT_LOCALE` 时返回该值；
   未设时与 `effective_ui_default_locale()` 一致（在测试中通过 monkeypatch 验证）。

5. **端到端渲染**：与 `tests/test_report_studio_template_locale.py` 互补（en/zh 全文、
   缺 zh 模板回退 en）；本文件聚焦「契约 + 目录」，避免重复重跑 last30days。

执行：

  poetry run pytest tests/test_acceptance_i18n_step5_report_studio.py \\
    tests/test_report_studio_template_locale.py -v
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adami_kernel.i18n.catalog import default_translator
from adami_kernel.peripheral.report_studio.report_renderer import localized_report_title

_LOCALES = Path(__file__).resolve().parents[1] / "src" / "adami_kernel" / "i18n" / "locales"

STEP5_CATALOG_KEYS: tuple[str, ...] = (
    "report.studio.kind_daily",
    "report.studio.kind_weekly",
    "report.studio.kind_monthly",
    "report.studio.title",
    "report.studio.meta_period",
    "report.studio.meta_timezone",
    "report.studio.meta_type",
    "report.studio.section_system",
    "report.studio.section_world_news",
    "report.studio.section_ai",
    "report.studio.section_market",
    "report.studio.collect_disclaimer",
    "report.studio.empty_world_news",
    "report.studio.empty_ai",
    "report.studio.empty_market",
    "report.studio.section_crypto",
    "report.studio.empty_crypto",
    "report.studio.crypto_fetch_failed",
    "report.studio.crypto_asof",
    "report.studio.source_link",
)


def _load_common(locale: str) -> dict[str, str]:
    p = _LOCALES / locale / "common.json"
    data = json.loads(p.read_text(encoding="utf-8"))
    return {str(k): str(v) for k, v in data.items()}


@pytest.mark.parametrize("key", STEP5_CATALOG_KEYS)
def test_step5_catalog_key_present_en_zh(key: str) -> None:
    en = _load_common("en")
    zh = _load_common("zh-Hans")
    assert key in en and key in zh
    assert en[key].strip() and zh[key].strip()
    assert en[key] != zh[key], f"{key}: en/zh should differ"


def test_step5_title_template_formats() -> None:
    tr = default_translator()
    for loc, kind_key, expect_substr in (
        ("en", "report.studio.kind_weekly", "Weekly"),
        ("zh-Hans", "report.studio.kind_weekly", "周报"),
    ):
        kind = tr.t(kind_key, locale=loc)
        title = tr.t("report.studio.title", kind=kind, locale=loc)
        assert expect_substr in title


def test_step5_packaged_j2_files_exist_and_use_labels() -> None:
    for loc in ("en", "zh-Hans"):
        p = _LOCALES / loc / "report.md.j2"
        assert p.is_file(), f"missing template: {p}"
        text = p.read_text(encoding="utf-8")
        assert "{{ labels." in text
        assert "{{ title }}" in text


@pytest.mark.parametrize(
    "rtype,locale,expect",
    (
        ("daily", "en", "Daily Report"),
        ("weekly", "en", "Weekly Report"),
        ("monthly", "zh-Hans", "月报简报"),
    ),
)
def test_step5_localized_document_title(rtype: str, locale: str, expect: str) -> None:
    assert localized_report_title(rtype, locale) == expect  # type: ignore[arg-type]


def test_step5_effective_report_locale_prefers_adami_report_locale(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import adami_kernel.config as cfg

    monkeypatch.setattr(cfg.settings, "ADAMI_REPORT_LOCALE", "zh-Hans", raising=False)
    monkeypatch.setattr(cfg.settings, "ADAMI_UI_LOCALE", "en", raising=False)
    monkeypatch.setattr(cfg.settings, "ADAMI_DEFAULT_LOCALE", "en", raising=False)
    assert cfg.settings.effective_report_locale() == "zh-Hans"
    assert cfg.settings.effective_ui_default_locale() == "en"


def test_step5_effective_report_locale_follows_ui_when_report_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import adami_kernel.config as cfg

    monkeypatch.setattr(cfg.settings, "ADAMI_REPORT_LOCALE", None, raising=False)
    monkeypatch.setattr(cfg.settings, "ADAMI_UI_LOCALE", "zh-Hans", raising=False)
    monkeypatch.setattr(cfg.settings, "ADAMI_DEFAULT_LOCALE", "en", raising=False)
    assert (
        cfg.settings.effective_report_locale()
        == cfg.settings.effective_ui_default_locale()
        == "zh-Hans"
    )
