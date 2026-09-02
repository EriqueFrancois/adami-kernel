from __future__ import annotations

import asyncio

import pytest

from adami_kernel.integration.sim.replay import (
    FaultInjectionOptions,
    ReplayValidationError,
    replay_inject_with_faults,
)
from adami_kernel.integration.sim.schema import ReplayTraceRecordV1


@pytest.mark.parametrize("skip_idx", [0, 1])
def test_fault_injection_skip_indices(skip_idx: int) -> None:
    recs = [
        ReplayTraceRecordV1(ts=1, trace_id="t", source_module="user.prompt", target_topic="system.events", payload_redacted={"i": 0}),
        ReplayTraceRecordV1(ts=2, trace_id="t", source_module="user.prompt", target_topic="system.events", payload_redacted={"i": 1}),
    ]
    seen: list[int] = []

    async def _inject(ev):
        seen.append(int(ev.payload.get("i")))

    faults = FaultInjectionOptions(enabled=True, skip_indices=frozenset({skip_idx}))
    asyncio.run(replay_inject_with_faults(recs, _inject, faults))
    assert seen == ([1] if skip_idx == 0 else [0])


def test_fault_injection_replace_payload_at() -> None:
    recs = [
        ReplayTraceRecordV1(ts=1, trace_id="t", source_module="user.prompt", target_topic="system.events", payload_redacted={"x": 1}),
        ReplayTraceRecordV1(ts=2, trace_id="t", source_module="user.prompt", target_topic="system.events", payload_redacted={"x": 2}),
    ]
    seen: list[int] = []

    async def _inject(ev):
        seen.append(int(ev.payload.get("x")))

    faults = FaultInjectionOptions(
        enabled=True,
        replace_payload_at={1: {"x": 999}},
    )
    asyncio.run(replay_inject_with_faults(recs, _inject, faults))
    assert seen == [1, 999]


def test_fault_injection_raise_indices() -> None:
    recs = [
        ReplayTraceRecordV1(ts=1, trace_id="t", source_module="user.prompt", target_topic="system.events", payload_redacted={"x": 1}),
        ReplayTraceRecordV1(ts=2, trace_id="t", source_module="user.prompt", target_topic="system.events", payload_redacted={"x": 2}),
    ]

    async def _inject(_ev):
        return None

    faults = FaultInjectionOptions(enabled=True, raise_indices={1: "boom"})
    with pytest.raises(ReplayValidationError):
        asyncio.run(replay_inject_with_faults(recs, _inject, faults))

