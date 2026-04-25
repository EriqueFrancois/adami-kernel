"""模块四步骤 7：长任务阶段与 Sim/telemetry 对齐（phase、checkpoint_seq、恢复可读性）。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from adami_kernel.config import settings
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.orchestrator.long_task_phase_gate import (
    emit_phase_transition_if_changed,
    extract_phase_sequence_from_history,
)
from adami_kernel.orchestrator.long_task_recovery import rollback_to_last_good_checkpoint
from adami_kernel.orchestrator.long_task_schema import LongTaskPhase
from adami_kernel.orchestrator.workflow_models import Node, WorkflowState
from adami_kernel.telemetry.experience_aggregator import ExperienceAggregator
from adami_kernel.telemetry.experience_sink import ExperienceSink


@pytest.fixture
def memory_db_path(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADAMI_L2_MEMORY_DB_PATH", str(tmp_path / "l2_phases.db"))
    return tmp_path


@pytest.mark.asyncio
async def test_extract_phase_sequence_includes_checkpoint_seq(memory_db_path):
    m = LayeredMemory()
    await m.initialize(start_periodic_cleanup=False)
    bus = MagicMock()
    bus.publish = AsyncMock()
    st = WorkflowState(
        chat_id="c1",
        metadata={"long_task_tracking_enabled": True},
        context={"current_phase": "research"},
        nodes={"__start__": Node(node_id="__start__", node_type="START")},
        edges={"__start__": []},
    )
    await emit_phase_transition_if_changed(
        st,
        m,
        bus,
        to_phase=LongTaskPhase.CODE,
        reason="route",
        source_module="test",
        gate_detail="dag_route",
        history_extras={"completed_node_id": "a", "next_node_id": "b"},
    )
    seq = extract_phase_sequence_from_history(st.history)
    assert len(seq) == 1
    assert seq[0]["to_phase"] == "code"
    assert seq[0].get("checkpoint_seq") == 1


@pytest.mark.asyncio
async def test_multi_phase_transitions_distinct_checkpoint_seq_per_phase(memory_db_path):
    m = LayeredMemory()
    await m.initialize(start_periodic_cleanup=False)
    bus = MagicMock()
    bus.publish = AsyncMock()
    st = WorkflowState(
        chat_id="c1",
        metadata={"long_task_tracking_enabled": True},
        context={"current_phase": "research"},
        nodes={"__start__": Node(node_id="__start__", node_type="START")},
        edges={"__start__": []},
    )
    await emit_phase_transition_if_changed(
        st,
        m,
        bus,
        to_phase=LongTaskPhase.CODE,
        reason="to_code",
        source_module="t",
        gate_detail="dag_route",
    )
    await emit_phase_transition_if_changed(
        st,
        m,
        bus,
        to_phase=LongTaskPhase.TEST,
        reason="to_test",
        source_module="t",
        gate_detail="dag_route",
    )
    seqs = [
        h.get("checkpoint_seq") for h in st.history if h.get("event_type") == "phase_transition"
    ]
    assert seqs == [1, 1]
    assert (await m.get_workflow_phase_checkpoint_record(st.workflow_id, "code"))["seq"] == 1
    assert (await m.get_workflow_phase_checkpoint_record(st.workflow_id, "test"))["seq"] == 1


@pytest.mark.asyncio
async def test_rollback_restores_context_from_last_good_after_phases(memory_db_path):
    m = LayeredMemory()
    await m.initialize(start_periodic_cleanup=False)
    bus = MagicMock()
    bus.publish = AsyncMock()
    st = WorkflowState(
        chat_id="c1",
        metadata={"long_task_tracking_enabled": True},
        nodes={"__start__": Node(node_id="__start__", node_type="START")},
        edges={"__start__": []},
    )
    await emit_phase_transition_if_changed(
        st,
        m,
        bus,
        to_phase=LongTaskPhase.CODE,
        reason="r1",
        source_module="t",
        gate_detail="dag_route",
    )
    st.context["current_phase"] = "broken"
    st.context["dirty"] = True
    ok = await rollback_to_last_good_checkpoint(st, m)
    assert ok is True
    assert st.context.get("current_phase") == "code"
    assert "phase_recovery_payload" in st.context


def test_experience_sink_phase_transition_record_fields(tmp_path):
    import json
    from datetime import datetime, timezone

    agg = ExperienceAggregator(tmp_path)
    sink = ExperienceSink(enabled=True, aggregator=agg)
    sink.begin_episode("wf_ep", "tr0", push_context=False)
    sink.record_phase_transition(
        trace_id="tr1",
        episode_id="wf_ep",
        from_phase="research",
        to_phase="code",
        checkpoint_seq=7,
        gate_detail="dag_route",
        source_module="unit",
        reason="test",
    )
    sink.end_episode("wf_ep", "success", pop_context=False)
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    p = tmp_path / day / "episodes.jsonl"
    assert p.is_file()
    line = p.read_text(encoding="utf-8").strip().splitlines()[-1]
    ep = json.loads(line)
    evs = ep.get("events") or []
    pt = [e for e in evs if e.get("type") == "phase_transition"]
    assert len(pt) == 1
    assert pt[0].get("phase") == "code"
    assert pt[0].get("checkpoint_seq") == 7
