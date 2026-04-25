"""Offline Report Studio → SecondBrain writer (no EventBus; curated providers stubbed).

Invoked by ``report_studio_to_secondbrain.sh``. Uses the same stack as
``tests/test_report_studio_template_locale.py`` (``generate_fixed_blocks_report`` +
``SecondBrainManager.write_inbox_note``) with RSS/GitHub/DDG paths mocked so CI
does not hit the network.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, patch


def _configure_demo_env(*, data_dir: Path, brain_root: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    os.environ["ADAMI_DATA_DIR"] = str(data_dir)
    os.environ["ADAMI_SECOND_BRAIN_ROOT"] = str(brain_root)
    os.environ["ADAMI_REPORT_CRYPTO_ENABLED"] = "false"
    os.environ["ADAMI_REPORT_TRANSLATE_NEWS"] = "false"


async def _generate_and_write(*, brain_root: Path) -> Path:
    from adami_kernel.hippocampus.second_brain import SecondBrainManager
    from adami_kernel.peripheral.report_studio.report_generator import (
        generate_fixed_blocks_report,
    )

    sb = SecondBrainManager(str(brain_root))

    async def search_fn(q: str, max_results: int):
        return [{"title": "demo", "href": "https://example.invalid", "body": "stub"}] * max_results

    now = datetime.now(timezone.utc)
    start = now - timedelta(days=1)

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
            period_start=start,
            period_end=now,
            second_brain=sb,
            search_fn=search_fn,
            locale="en",
        )

    note_title = f"report: daily ({now.strftime('%Y-%m-%d')})"
    body_md = rep.rendered.body_md
    return sb.write_inbox_note(
        note_title,
        body_md,
        tags=["report", "daily"],
        source="report_studio",
        dedupe_key=f"report:daily:{now.strftime('%Y-%m-%d')}",
        filename_prefix="report",
    )


async def _amain() -> int:
    parser = argparse.ArgumentParser(description="Write a demo daily report into SecondBrain Inbox.")
    parser.add_argument(
        "--brain-root",
        type=Path,
        default=None,
        help="SecondBrain root (default: temp directory under $TMPDIR)",
    )
    args = parser.parse_args()

    if args.brain_root is not None:
        root = args.brain_root.expanduser().resolve()
        data_dir = root.parent / f".adami_data_demo_{root.name}"
        _configure_demo_env(data_dir=data_dir, brain_root=root)
    else:
        tmp = Path(tempfile.mkdtemp(prefix="adami_report_demo_"))
        _configure_demo_env(data_dir=tmp / "data", brain_root=tmp / "brain")

    # Import settings-dependent modules only after env is set.
    try:
        out = await _generate_and_write(brain_root=Path(os.environ["ADAMI_SECOND_BRAIN_ROOT"]))
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    print(out)
    return 0


def main() -> int:
    return asyncio.run(_amain())


if __name__ == "__main__":
    raise SystemExit(main())
