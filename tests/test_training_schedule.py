"""定时训练调度：墙钟计算与 run_training_job 衔接（不实际睡一晚）。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from adami_kernel.training.run_trainer import run_training_job
from adami_kernel.training.schedule import seconds_until_next_local_time


def test_seconds_until_next_local_time_is_positive() -> None:
    d = seconds_until_next_local_time(hour=3, minute=0, tz_name="Asia/Shanghai")
    assert 0 < d <= 24 * 3600


def test_seconds_until_fixed_wall_clock_utc() -> None:
    tz = ZoneInfo("UTC")
    fixed_now = datetime(2030, 1, 1, 2, 0, 0, tzinfo=tz)
    with patch("adami_kernel.training.schedule.datetime") as mock_dt:
        mock_dt.now.return_value = fixed_now
        s = seconds_until_next_local_time(hour=3, minute=0, tz_name="UTC")
    assert abs(s - 3600.0) < 0.01


def test_run_training_job_returns_3_on_empty_dir(tmp_path: Path) -> None:
    empty = tmp_path / "e"
    empty.mkdir()
    out = tmp_path / "o"
    code = run_training_job(
        experience_dir=empty,
        output_dir=out,
        dry_run=True,
        emit_stderr_messages=False,
    )
    assert code == 3
