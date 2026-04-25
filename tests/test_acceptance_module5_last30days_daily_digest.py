from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

import pytest

from adami_kernel.config import settings
from adami_kernel.nexus.event import AdamiEvent
from adami_kernel.peripheral.circadian_nerve import CircadianNerve


class _FakeBus:
    def __init__(self) -> None:
        self.events: List[AdamiEvent] = []

    async def publish(self, event: AdamiEvent) -> None:
        self.events.append(event)


@pytest.mark.asyncio
async def test_circadian_publishes_last30days_daily_event(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = _FakeBus()
    nerve = CircadianNerve(bus, default_chat_id=123)

    monkeypatch.setattr(settings, "ADAMI_LAST30DAYS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ADAMI_LAST30DAYS_DAILY_TOPIC", "AI Agents", raising=False)
    monkeypatch.setattr(settings, "ADAMI_LAST30DAYS_WEEKLY_TOPIC", "", raising=False)
    monkeypatch.setattr(settings, "ADAMI_LAST30DAYS_WRITE_TO", "Inbox", raising=False)
    monkeypatch.setattr(settings, "ADAMI_LAST30DAYS_EMIT_MODE", "context", raising=False)
    monkeypatch.setattr(settings, "ADAMI_LAST30DAYS_REFRESH_DEFAULT", False, raising=False)

    now = datetime(2026, 4, 13, 9, 0, 0, tzinfo=timezone(timedelta(hours=8)))  # Monday 09:00 BJT
    await nerve._trigger_morning_routine(now, is_test=True)

    # At least: 1 morning report + 1 last30days daily digest
    assert len(bus.events) >= 2
    last = [e for e in bus.events if "circadian_last30days_daily" in str(e.trace_id)]
    assert last, "expected daily last30days event"
    ev = last[0]
    assert ev.target_topic == "system.events"
    assert ev.payload.get("chat_id") == "123"
    task = str(ev.payload.get("task") or "")
    assert "LAST30DAYS_DIGEST" in task
    assert "AI Agents" in task


@pytest.mark.asyncio
async def test_circadian_publishes_weekly_on_monday(monkeypatch: pytest.MonkeyPatch) -> None:
    bus = _FakeBus()
    nerve = CircadianNerve(bus, default_chat_id=9)

    monkeypatch.setattr(settings, "ADAMI_LAST30DAYS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ADAMI_LAST30DAYS_DAILY_TOPIC", "", raising=False)
    monkeypatch.setattr(settings, "ADAMI_LAST30DAYS_WEEKLY_TOPIC", "Weekly AI", raising=False)
    monkeypatch.setattr(settings, "ADAMI_LAST30DAYS_WRITE_TO", "Resources", raising=False)
    monkeypatch.setattr(settings, "ADAMI_LAST30DAYS_EMIT_MODE", "md", raising=False)
    monkeypatch.setattr(settings, "ADAMI_LAST30DAYS_REFRESH_DEFAULT", True, raising=False)

    now = datetime(2026, 4, 13, 9, 0, 0, tzinfo=timezone(timedelta(hours=8)))  # Monday
    await nerve._trigger_morning_routine(now, is_test=True)

    weekly = [e for e in bus.events if "circadian_last30days_weekly" in str(e.trace_id)]
    assert weekly, "expected weekly event on Monday"
    task = str(weekly[0].payload.get("task") or "")
    assert "Weekly AI" in task
    assert '"write_to": "Resources"' in task
    assert '"emit": "md"' in task
    assert '"refresh": true' in task.lower()


@pytest.mark.asyncio
async def test_circadian_last30days_cooldown_skips_second_trigger(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bus = _FakeBus()
    nerve = CircadianNerve(bus, default_chat_id=1)

    monkeypatch.setattr(settings, "ADAMI_LAST30DAYS_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "ADAMI_LAST30DAYS_DAILY_TOPIC", "X", raising=False)
    monkeypatch.setattr(settings, "ADAMI_LAST30DAYS_WEEKLY_TOPIC", "", raising=False)

    now = datetime(2026, 4, 15, 9, 0, 0, tzinfo=timezone(timedelta(hours=8)))
    await nerve._trigger_morning_routine(now, is_test=True)
    first = len([e for e in bus.events if "circadian_last30days_daily" in str(e.trace_id)])
    await nerve._trigger_morning_routine(now, is_test=True)
    second = len([e for e in bus.events if "circadian_last30days_daily" in str(e.trace_id)])
    assert first == 1
    assert second == 1, "second trigger should be skipped by cooldown"
