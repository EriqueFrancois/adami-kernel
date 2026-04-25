from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import List

import pytest

from adami_kernel.nexus.event import AdamiEvent
from adami_kernel.peripheral.report_studio.report_config import ReportConfig, ReportSchedule
from adami_kernel.peripheral.report_studio.report_scheduler import ReportScheduler


class _FakeBus:
    def __init__(self) -> None:
        self.events: List[AdamiEvent] = []

    async def publish(self, event: AdamiEvent) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_scheduler_due_now_daily_fires_once_per_day() -> None:
    bus = _FakeBus()
    sched = ReportScheduler(bus, default_chat_id=7)

    cfg = ReportConfig(
        report_type="daily",
        enabled=True,
        schedule=ReportSchedule(timezone="UTC", publish_time_hhmm="09:00"),
    )
    now = datetime(2026, 1, 2, 9, 0, 0, tzinfo=timezone.utc)
    assert sched._due_now(cfg=cfg, now_utc=now) is True
    await sched._publish_run_event("daily")
    sched._last_fired["daily"] = SimpleNamespace(date_key="2026-01-02", fired_at_ts=now.timestamp())
    assert sched._due_now(cfg=cfg, now_utc=now) is False


@pytest.mark.asyncio
async def test_scheduler_publishes_report_run_event() -> None:
    bus = _FakeBus()
    sched = ReportScheduler(bus, default_chat_id=123)
    await sched._publish_run_event("weekly")
    assert bus.events
    ev = bus.events[0]
    assert ev.target_topic == "system.events"
    assert ev.payload.get("chat_id") == "123"
    assert "/report run weekly" in str(ev.payload.get("task") or "")
