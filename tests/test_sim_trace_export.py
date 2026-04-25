"""模块三步骤 1：EventBus 轨迹 NDJSON 导出。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import adami_kernel.config as config_mod
from adami_kernel.integration.sim.schema import TRACE_SCHEMA_V1
from adami_kernel.integration.sim.trace_sink import (
    event_to_record,
    get_trace_sink,
    reset_sim_trace_sink_for_tests,
)
from adami_kernel.nexus.bus import EventBus
from adami_kernel.nexus.event import AdamiEvent, EventPriority
from adami_kernel.telemetry.experience_sink import experience_episode_id_ctx


async def _stop_bus_dlq(bus: EventBus) -> None:
    t = getattr(bus, "_replay_task", None)
    if t and not t.done():
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass


def test_event_to_record_redacts_api_key_field() -> None:
    ev = AdamiEvent(
        trace_id="t-redact",
        source_module="sensory.cli",
        target_topic="system.events",
        priority=EventPriority.HIGH,
        payload={"task": "x", "api_key": "sk-abcdefghijklmnopqrstuvwxyz123456"},
    )
    rec = event_to_record(ev)
    dumped = rec.model_dump()
    assert dumped["schema_version"] == TRACE_SCHEMA_V1
    assert dumped["trace_id"] == "t-redact"
    assert dumped["payload_redacted"].get("api_key") == "[REDACTED]"
    line = rec.to_ndjson_line()
    assert "sk-abc" not in line


def test_event_to_record_phase_transition_populates_top_level_fields() -> None:
    ev = AdamiEvent(
        trace_id="t-phase",
        source_module="workflow.phase_gate",
        target_topic="workflow.events",
        priority=EventPriority.NORMAL,
        payload={
            "workflow_id": "wf1",
            "chat_id": "c1",
            "event_type": "PHASE_TRANSITION",
            "from_phase": "research",
            "to_phase": "code",
            "phase": "code",
            "checkpoint_seq": 2,
            "gate_detail": "dag_route",
        },
    )
    rec = event_to_record(ev)
    assert rec.phase == "code"
    assert rec.checkpoint_seq == 2
    assert rec.payload_redacted.get("event_type") == "PHASE_TRANSITION"


def test_event_to_record_episode_id_from_context() -> None:
    tok = experience_episode_id_ctx.set("ep-ctx-1")
    try:
        ev = AdamiEvent(
            trace_id="t-ep",
            source_module="cortex.x",
            target_topic="system.events",
            priority=EventPriority.NORMAL,
            payload={},
        )
        assert event_to_record(ev).episode_id == "ep-ctx-1"
    finally:
        experience_episode_id_ctx.reset(tok)


@pytest.mark.asyncio
async def test_bus_publish_writes_ndjson_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    await reset_sim_trace_sink_for_tests()
    out = tmp_path / "trace.ndjson"
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_MODULE_ENABLED", True)
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", True)
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_TRACE_EXPORT_PATH", str(out))
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_TRACE_FLUSH_INTERVAL_SEC", 0.05)
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_TRACE_BATCH_SIZE", 4)
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_TRACE_MAX_QUEUE", 256)

    bus = EventBus()
    await bus.initialize()
    await bus.subscribe("system.events")
    ev = AdamiEvent(
        trace_id="cli_trace_1",
        source_module="sensory.cli",
        target_topic="system.events",
        priority=EventPriority.HIGH,
        payload={"task": "hello", "platform": "cli"},
    )
    assert await bus.publish(ev) is True
    await asyncio.sleep(0.3)
    await get_trace_sink().stop()
    await _stop_bus_dlq(bus)
    text = out.read_text(encoding="utf-8")
    assert text.strip()
    row = json.loads(text.strip().split("\n")[0])
    assert row["schema_version"] == TRACE_SCHEMA_V1
    assert row["trace_id"] == "cli_trace_1"
    assert "Bearer" not in text


@pytest.mark.asyncio
async def test_system_event_branch_traced(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    await reset_sim_trace_sink_for_tests()
    out = tmp_path / "sys.ndjson"
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_MODULE_ENABLED", True)
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", True)
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_TRACE_EXPORT_PATH", str(out))
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_TRACE_FLUSH_INTERVAL_SEC", 0.05)
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_TRACE_BATCH_SIZE", 1)

    bus = EventBus()
    await bus.initialize()
    await bus.subscribe("system.events")
    ev = AdamiEvent(
        trace_id="circadian_test_1",
        source_module="peripheral.circadian",
        target_topic="system.events",
        priority=EventPriority.LOW,
        payload={"kind": "tick"},
    )
    assert await bus.publish(ev) is True
    await asyncio.sleep(0.25)
    await get_trace_sink().stop()
    await _stop_bus_dlq(bus)
    assert "circadian_test_1" in out.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_topic_allowlist_filters(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    await reset_sim_trace_sink_for_tests()
    out = tmp_path / "filt.ndjson"
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_MODULE_ENABLED", True)
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", True)
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_TRACE_EXPORT_PATH", str(out))
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_TRACE_TOPICS_ALLOWLIST", ["other.topic"])
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_TRACE_FLUSH_INTERVAL_SEC", 0.05)
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_TRACE_BATCH_SIZE", 1)

    bus = EventBus()
    await bus.initialize()
    await bus.subscribe("system.events")
    ev = AdamiEvent(
        trace_id="t1",
        source_module="sensory.cli",
        target_topic="system.events",
        priority=EventPriority.HIGH,
        payload={},
    )
    await bus.publish(ev)
    await asyncio.sleep(0.2)
    await get_trace_sink().stop()
    await _stop_bus_dlq(bus)
    assert not out.exists() or out.read_text(encoding="utf-8").strip() == ""


@pytest.mark.asyncio
async def test_many_events_bounded_queue(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    await reset_sim_trace_sink_for_tests()
    data_root = tmp_path / "adata"
    data_root.mkdir()
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_MODULE_ENABLED", True)
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", True)
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_TRACE_EXPORT_PATH", None)
    monkeypatch.setattr(config_mod.settings, "ADAMI_DATA_DIR", str(data_root))
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_TRACE_MAX_QUEUE", 64)
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_TRACE_BATCH_SIZE", 32)
    monkeypatch.setattr(config_mod.settings, "ADAMI_SIM_TRACE_FLUSH_INTERVAL_SEC", 0.01)

    bus = EventBus()
    await bus.initialize()
    await bus.subscribe("system.events")
    for i in range(1000):
        ev = AdamiEvent(
            trace_id=f"stress_{i}",
            source_module="sensory.cli",
            target_topic="system.events",
            priority=EventPriority.NORMAL,
            payload={"i": i},
        )
        await bus.publish(ev)
    await asyncio.sleep(3.0)
    await get_trace_sink().stop()
    await _stop_bus_dlq(bus)
    path = data_root / "traces" / "eventbus.ndjson"
    assert path.is_file()
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert 32 <= len(lines) <= 1200, "bounded queue + worker should persist many lines without OOM"
