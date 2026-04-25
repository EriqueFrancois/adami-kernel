from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

import adami_kernel.config as config
from adami_kernel.hippocampus.second_brain import SecondBrainManager
from adami_kernel.peripheral.report_studio.report_generator import generate_fixed_blocks_report
from adami_kernel.peripheral.report_studio.report_providers import (
    ProviderItem,
    filter_items_by_explicit_calendar_dates,
)


def _write_fake_last30days(tmp_path: Path) -> Path:
    p = tmp_path / "fake_last30days.py"
    p.write_text(
        """
import argparse, sys
parser = argparse.ArgumentParser()
parser.add_argument("topic")
parser.add_argument("--emit", default="context")
parser.add_argument("--sources", default="auto")
parser.add_argument("--refresh", action="store_true")
args = parser.parse_args()
# output a few bullet lines
print(f"- {args.topic} item1")
print(f"- {args.topic} item2")
print(f"- {args.topic} item3")
""".lstrip(),
        encoding="utf-8",
    )
    return p


@pytest.mark.asyncio
async def test_generate_fixed_blocks_report_renders_markdown(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fake = _write_fake_last30days(tmp_path)
    # Patch settings used by last30days bridge
    monkeypatch.setattr(config.settings, "ADAMI_LAST30DAYS_SCRIPT_PATH", str(fake), raising=False)
    monkeypatch.setattr(config.settings, "ADAMI_LAST30DAYS_PYTHON", sys.executable, raising=False)
    monkeypatch.setattr(config.settings, "ADAMI_REPORT_CRYPTO_ENABLED", False, raising=False)
    monkeypatch.setattr(config.settings, "ADAMI_REPORT_TRANSLATE_NEWS", False, raising=False)

    # Create a brain root for template seeding
    sb = SecondBrainManager(str(tmp_path / "brain"))

    async def search_fn(q: str, max_results: int):
        return [{"title": "t", "href": "h", "body": "b"}] * max_results

    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    with (
        patch(
            "adami_kernel.peripheral.report_studio.curated_report_providers.aggregate_whitelist_rss",
            new=AsyncMock(return_value=([], [])),
        ),
        patch(
            "adami_kernel.peripheral.report_studio.curated_report_providers.github_ai_repo_items_for_report",
            new=AsyncMock(return_value=([], None, None)),
        ),
        patch(
            "adami_kernel.peripheral.report_studio.curated_report_providers.world_web_hotspot_provider",
            new=AsyncMock(return_value=[]),
        ),
    ):
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
    # Section titles follow ``report.studio.section_*`` in locales/en/common.json
    assert "World & business news" in md or "Global news highlights" in md
    assert "GitHub top repos & AI media" in md or "AI technology progress" in md
    assert "Markets" in md or "Global financial markets" in md


def test_filter_items_by_explicit_calendar_dates() -> None:
    ps = datetime(2026, 4, 10, tzinfo=timezone.utc)
    pe = datetime(2026, 4, 11, tzinfo=timezone.utc)
    items = [
        ProviderItem("stale", "Event on 2026-04-05 reported"),
        ProviderItem("in_window", "Update 2026-04-10 details"),
        ProviderItem("no_date", "No ISO date in this blurb"),
    ]
    out = filter_items_by_explicit_calendar_dates(items, period_start=ps, period_end=pe)
    titles = {x.title for x in out}
    assert "stale" not in titles
    assert "in_window" in titles
    assert "no_date" in titles
