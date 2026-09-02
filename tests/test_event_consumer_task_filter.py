from __future__ import annotations

import asyncio
import contextlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from adami_kernel.core.lifecycle_manager import LifecycleManager
from adami_kernel.nexus.bus import EventBus
from adami_kernel.nexus.event import AdamiEvent, EventPriority


@pytest.mark.asyncio
async def test_event_consumer_skips_events_without_task(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regression: internal/telemetry records on system.events must not re-enter DP routing."""

    bus = EventBus()
    await bus.initialize()

    comps = {"bus": bus}
    lm = LifecycleManager(comps)  # type: ignore[arg-type]
    # Minimal KernelContext fields referenced by DP on the tested paths.
    lm.memory = MagicMock()
    lm.router = MagicMock()
    lm.toolbox = MagicMock()
    lm.immunity = MagicMock()
    lm.intent_router = MagicMock(route_task=AsyncMock(return_value=("DIRECT_ANSWER", "ok")))
    lm.prompt_builder = MagicMock()
    lm.chat_locale_overrides = {}

    # Patch DecisionProcessor.process to count invocations without pulling full router stack.
    called = SimpleNamespace(n=0)

    async def _fake_process(_self, _event):  # noqa: ANN001
        called.n += 1

    monkeypatch.setattr(
        "adami_kernel.cortex.decision_processor.DecisionProcessor.process",
        _fake_process,
    )

    consumer = asyncio.create_task(lm._event_consumer())
    await asyncio.sleep(0.05)

    # Event without task: should be skipped.
    await bus.publish(
        AdamiEvent(
            trace_id="t0",
            source_module="cortex.router",
            target_topic="system.events",
            priority=EventPriority.NORMAL,
            payload={"chat_id": "default", "task": ""},
        )
    )
    # Normal user event: should be processed once.
    await bus.publish(
        AdamiEvent(
            trace_id="t1",
            source_module="user.prompt",
            target_topic="system.events",
            priority=EventPriority.HIGH,
            payload={"chat_id": "cli", "task": "hello"},
        )
    )

    await asyncio.sleep(0.2)

    lm._running = False
    consumer.cancel()
    with contextlib.suppress(BaseException):
        await consumer

    assert called.n == 1

