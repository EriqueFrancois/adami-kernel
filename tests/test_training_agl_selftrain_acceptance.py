"""Agent Lightning 自训练（定时 + 闲置）补充验收。

ST-1  ``run_training_job_sync_blocking`` 可导入且返回整型退出码。
ST-2  ``train_job_lock`` 与 ``schedule`` 模块导出一致。
ST-3  闲置循环在「已满足空闲阈值」时调用一次阻塞训练函数（打桩 ``idle_schedule._idle_sleep`` / 训练函数）。
ST-4  配置字段 ``ADAMI_IDLE_TRAIN_*`` 在 ``config.Settings`` 中存在且类型合理。

与 ``tests/test_training_phase4_acceptance.py``、``tests/test_phase5_agl_acceptance.py`` 一并执行：

``poetry run pytest tests/test_training_phase4_acceptance.py tests/test_phase5_agl_acceptance.py tests/test_activity_clock.py tests/test_training_schedule.py tests/test_training_agl_selftrain_acceptance.py -q``
"""

from __future__ import annotations

import asyncio
import contextlib

import pytest

from adami_kernel.config import settings
from adami_kernel.training import idle_schedule as isched
from adami_kernel.training import schedule as train_sched


def test_st1_run_training_job_sync_blocking_returns_int(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    root = tmp_path / "exp"
    day = root / "2030-01-01"
    day.mkdir(parents=True)
    from adami_kernel.training.experience_to_rollouts import ExperienceEpisode

    ep = ExperienceEpisode(
        episode_id="st1",
        primary_trace_id="t",
        status="success",
        meta={"task": "t"},
        events=[],
    )
    (day / "episodes.jsonl").write_text(ep.model_dump_json() + "\n", encoding="utf-8")
    monkeypatch.setattr(settings, "ADAMI_EXPERIENCE_DIR", root)
    monkeypatch.setattr(settings, "ADAMI_POLICY_DIR", tmp_path / "pol")
    monkeypatch.setattr(settings, "ADAMI_TRAIN_SCHEDULE_DRY_RUN", True)
    code = train_sched.run_training_job_sync_blocking()
    assert isinstance(code, int)
    assert code in (0, 2, 3)


def test_st2_train_job_lock_is_shared_asyncio_lock() -> None:
    assert isinstance(train_sched.train_job_lock, asyncio.Lock)


def test_st4_idle_train_settings_exist() -> None:
    assert hasattr(settings, "ADAMI_IDLE_TRAIN_ENABLED")
    assert hasattr(settings, "ADAMI_IDLE_TRAIN_AFTER_SEC")
    assert hasattr(settings, "ADAMI_IDLE_TRAIN_POLL_SEC")
    assert hasattr(settings, "ADAMI_IDLE_TRAIN_COOLDOWN_SEC")
    assert float(settings.ADAMI_IDLE_TRAIN_AFTER_SEC) >= 60.0
    assert float(settings.ADAMI_IDLE_TRAIN_POLL_SEC) >= 5.0


@pytest.mark.asyncio
async def test_st3_idle_loop_invokes_training_when_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def fake_blocking() -> int:
        calls.append(1)
        return 0

    monkeypatch.setattr(isched, "run_training_job_sync_blocking", fake_blocking)
    monkeypatch.setattr(isched, "seconds_since_user_activity", lambda: 99999.0)
    monkeypatch.setattr(isched, "_last_idle_train_monotonic", 0.0)

    async def no_sleep(_: float) -> None:
        return None

    monkeypatch.setattr(isched, "_idle_sleep", no_sleep)
    monkeypatch.setattr(settings, "ADAMI_IDLE_TRAIN_ENABLED", True)
    monkeypatch.setattr(settings, "ADAMI_IDLE_TRAIN_AFTER_SEC", 1.0)
    monkeypatch.setattr(settings, "ADAMI_IDLE_TRAIN_POLL_SEC", 5.0)
    monkeypatch.setattr(settings, "ADAMI_IDLE_TRAIN_COOLDOWN_SEC", 0.0)

    t = asyncio.create_task(isched.idle_training_loop())
    await asyncio.sleep(0.05)
    t.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await t

    assert calls, "idle loop should invoke run_training_job_sync_blocking when idle"
