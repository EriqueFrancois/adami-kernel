"""Monotonic clock for user-facing activity (idle-time training gate)."""

from __future__ import annotations

import time
from threading import Lock

from adami_kernel.nexus.event import AdamiEvent

_lock = Lock()
_last_user_activity_monotonic = time.monotonic()


def touch_user_activity_from_event(event: AdamiEvent) -> None:
    """Advance the clock for events that represent interactive work.

    Scheduled report runs, circadian digests, etc. are excluded so they do not
    mask true user idle time.
    """
    tid = (event.trace_id or "").lower()
    src = event.source_module or ""
    if tid.startswith("report_sched_"):
        return
    if tid.startswith("circadian_"):
        return
    if "report_scheduler" in src or "circadian" in src.lower():
        return
    global _last_user_activity_monotonic
    with _lock:
        _last_user_activity_monotonic = time.monotonic()


def seconds_since_user_activity() -> float:
    with _lock:
        return time.monotonic() - _last_user_activity_monotonic
