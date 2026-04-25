"""User-activity clock for idle-gated training."""

from __future__ import annotations

import time

import pytest

from adami_kernel.nexus.event import AdamiEvent, EventPriority
from adami_kernel.observability import activity_clock as ac


@pytest.fixture(autouse=True)
def reset_activity_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ac, "_last_user_activity_monotonic", time.monotonic())


def test_touch_skips_report_scheduler_source() -> None:
    user_ev = AdamiEvent(
        trace_id="cli-1",
        source_module="nexus.shell",
        target_topic="system.events",
        priority=EventPriority.HIGH,
        payload={"task": "hi", "chat_id": "1"},
    )
    ac.touch_user_activity_from_event(user_ev)
    time.sleep(0.04)
    sched_ev = AdamiEvent(
        trace_id="x",
        source_module="peripheral.report_scheduler",
        target_topic="system.events",
        priority=EventPriority.NORMAL,
        payload={"task": "/report run daily", "chat_id": "1"},
    )
    ac.touch_user_activity_from_event(sched_ev)
    assert ac.seconds_since_user_activity() >= 0.035


def test_touch_skips_circadian_trace() -> None:
    ev = AdamiEvent(
        trace_id="circadian_digest_1",
        source_module="peripheral.circadian",
        target_topic="system.events",
        priority=EventPriority.HIGH,
        payload={"task": "digest", "chat_id": "9"},
    )
    t0 = ac.seconds_since_user_activity()
    ac.touch_user_activity_from_event(ev)
    assert abs(ac.seconds_since_user_activity() - t0) < 0.05


def test_touch_advances_for_user_event() -> None:
    ev = AdamiEvent(
        trace_id="cli-1",
        source_module="nexus.shell",
        target_topic="system.events",
        priority=EventPriority.HIGH,
        payload={"task": "hello", "chat_id": "default"},
    )
    time.sleep(0.05)
    ac.touch_user_activity_from_event(ev)
    assert ac.seconds_since_user_activity() < 0.2
