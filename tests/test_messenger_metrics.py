"""Tests for OpenTelemetry messenger notification counters (step 7)."""

from __future__ import annotations

import importlib

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader


def _sum_counter(reader: InMemoryMetricReader, name: str, attr_filter: dict[str, str]) -> float:
    total = 0.0
    for rm in reader.get_metrics_data().resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                if m.name != name:
                    continue
                for dp in m.data.data_points:
                    if all(dp.attributes.get(k) == v for k, v in attr_filter.items()):
                        total += float(dp.value)
    return total


def test_messenger_metrics_counters_recorded() -> None:
    reader = InMemoryMetricReader()
    metrics.set_meter_provider(MeterProvider(metric_readers=[reader]))
    mm = importlib.import_module("adami_kernel.observability.messenger_metrics")
    importlib.reload(mm)

    mm.record_notification_send("telegram", "send_message", "success")
    mm.record_notification_send("discord", "send_message", "failure")
    mm.record_notification_retry("telegram", "boot_pending_queue")

    assert (
        _sum_counter(
            reader,
            "adami.kernel.messenger.notifications",
            {"messaging.platform": "telegram", "messaging.outcome": "success"},
        )
        == 1.0
    )
    assert (
        _sum_counter(
            reader,
            "adami.kernel.messenger.notifications",
            {"messaging.platform": "discord", "messaging.outcome": "failure"},
        )
        == 1.0
    )
    assert (
        _sum_counter(
            reader,
            "adami.kernel.messenger.notification_retries",
            {"messaging.platform": "telegram"},
        )
        == 1.0
    )
