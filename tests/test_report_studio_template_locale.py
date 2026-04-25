"""Step 5: Report Studio locale templates + catalog labels."""

from __future__ import annotations

import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import adami_kernel.config as config
from adami_kernel.hippocampus.second_brain import SecondBrainManager
from adami_kernel.peripheral.report_studio import report_renderer as report_renderer_mod
from adami_kernel.peripheral.report_studio.report_generator import generate_fixed_blocks_report
from adami_kernel.peripheral.report_studio.report_renderer import (
    ReportRenderer,
    ReportTemplateStore,
)


def _write_fake_last30days(tmp_path: Path) -> Path:
    p = tmp_path / "fake_last30days.py"
    p.write_text(
        """
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("topic")
parser.add_argument("--emit", default="context")
parser.add_argument("--sources", default="auto")
parser.add_argument("--refresh", action="store_true")
args = parser.parse_args()
print(f"- {args.topic} item1")
print(f"- {args.topic} item2")
""".lstrip(),
        encoding="utf-8",
    )
    return p


@pytest.mark.asyncio
async def test_report_en_labels_and_title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _write_fake_last30days(tmp_path)
    monkeypatch.setattr(config.settings, "ADAMI_LAST30DAYS_SCRIPT_PATH", str(fake), raising=False)
    monkeypatch.setattr(config.settings, "ADAMI_LAST30DAYS_PYTHON", sys.executable, raising=False)
    monkeypatch.setattr(config.settings, "ADAMI_REPORT_CRYPTO_ENABLED", False, raising=False)
    monkeypatch.setattr(config.settings, "ADAMI_REPORT_TRANSLATE_NEWS", False, raising=False)

    sb = SecondBrainManager(str(tmp_path / "brain"))

    async def search_fn(q: str, max_results: int):
        return [{"title": "t", "href": "h", "body": "b"}] * max_results

    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    rep = await generate_fixed_blocks_report(
        report_type="daily",
        title=None,
        timezone_name="UTC",
        period_start=now - timedelta(days=1),
        period_end=now,
        second_brain=sb,
        search_fn=search_fn,
        locale="en",
    )
    md = rep.rendered.body_md
    assert "# Daily Report" in md
    assert "System self-updates" in md
    assert "World & business news" in md or "Global news highlights" in md
    assert "Period:" in md or "Period" in md


@pytest.mark.asyncio
async def test_report_zh_labels_and_title(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _write_fake_last30days(tmp_path)
    monkeypatch.setattr(config.settings, "ADAMI_LAST30DAYS_SCRIPT_PATH", str(fake), raising=False)
    monkeypatch.setattr(config.settings, "ADAMI_LAST30DAYS_PYTHON", sys.executable, raising=False)
    monkeypatch.setattr(config.settings, "ADAMI_REPORT_CRYPTO_ENABLED", False, raising=False)
    monkeypatch.setattr(config.settings, "ADAMI_REPORT_TRANSLATE_NEWS", False, raising=False)

    sb = SecondBrainManager(str(tmp_path / "brain"))

    async def search_fn(q: str, max_results: int):
        return [{"title": "t", "href": "h", "body": "b"}] * max_results

    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    rep = await generate_fixed_blocks_report(
        report_type="daily",
        title=None,
        timezone_name="UTC",
        period_start=now - timedelta(days=1),
        period_end=now,
        second_brain=sb,
        search_fn=search_fn,
        locale="zh-Hans",
    )
    md = rep.rendered.body_md
    assert "# 日报简报" in md or "日报简报" in md
    assert "系统自我更新" in md
    assert "国际与财经要闻" in md
    assert "周期" in md


def test_packaged_template_fallback_to_en_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Missing ``locales/zh-Hans/report.md.j2`` under a stub root uses en file; labels stay zh."""
    real_en = report_renderer_mod._PACKAGED_LOCALES_DIR / "en" / "report.md.j2"
    assert real_en.is_file(), "packaged en template must exist"
    stub = tmp_path / "locales"
    (stub / "en").mkdir(parents=True)
    shutil.copy(real_en, stub / "en" / "report.md.j2")
    monkeypatch.setattr(report_renderer_mod, "_PACKAGED_LOCALES_DIR", stub)

    sb = SecondBrainManager(str(tmp_path / "brain"))
    store = ReportTemplateStore(sb)
    text, path = store.load_locale_template("zh-Hans", supported=("en", "zh-Hans"))
    assert "en" in path.replace("\\", "/")
    assert "{{ title }}" in text

    renderer = ReportRenderer(sb)
    out = renderer.render(
        report_type="daily",
        title="T",
        period_start="a",
        period_end="b",
        timezone="UTC",
        data={
            "system_updates": {"top_n": 1, "items": []},
            "world_news": {"top_n": 1, "items": []},
            "ai_progress": {"top_n": 1, "items": []},
            "market_moves": {"top_n": 1, "items": []},
            "crypto_spot": {"items": [], "error": None, "error_user": None},
        },
        locale="zh-Hans",
        supported_locales=("en", "zh-Hans"),
    )
    assert "系统自我更新" in out.body_md
