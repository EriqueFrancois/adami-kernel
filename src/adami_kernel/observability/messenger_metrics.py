"""
OpenTelemetry metrics for Discord/Telegram outbound notification paths.

Counters support failure-rate dashboards (outcome=success|failure|skipped) and
retry visibility (``adami.kernel.messenger.notification_retries``).
"""

from __future__ import annotations

from typing import Optional

from opentelemetry import metrics

_METER_NAME = "adami_kernel.observability.messenger"
_send_counter: Optional[metrics.Counter] = None
_retry_counter: Optional[metrics.Counter] = None


def _send_c() -> metrics.Counter:
    global _send_counter
    if _send_counter is None:
        _send_counter = metrics.get_meter(_METER_NAME).create_counter(
            name="adami.kernel.messenger.notifications",
            unit="1",
            description="Outbound messenger sends (Discord/Telegram) by path and outcome.",
        )
    return _send_counter


def _retry_c() -> metrics.Counter:
    global _retry_counter
    if _retry_counter is None:
        _retry_counter = metrics.get_meter(_METER_NAME).create_counter(
            name="adami.kernel.messenger.notification_retries",
            unit="1",
            description="Scheduled retry attempts after a failed messenger notification send.",
        )
    return _retry_counter


def record_notification_send(platform: str, method: str, outcome: str) -> None:
    """Record one send attempt (``outcome``: success, failure, or skipped)."""
    _send_c().add(
        1,
        {
            "messaging.platform": str(platform).lower(),
            "messaging.method": str(method),
            "messaging.outcome": str(outcome),
        },
    )


def record_notification_retry(platform: str, context: str) -> None:
    """Record that a retry will occur after a failed attempt (boot loops, UI resend, etc.)."""
    _retry_c().add(
        1,
        {
            "messaging.platform": str(platform).lower(),
            "messaging.retry_context": str(context)[:120],
        },
    )
