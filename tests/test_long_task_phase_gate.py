"""模块四步骤 3：阶段闸 history、context、总线 PHASE_TRANSITION。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from adami_kernel.config import settings
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.nexus.event import AdamiEvent
from adami_kernel.orchestrator.long_task_phase_gate import (
    emit_phase_transition_if_changed,
    extract_phase_sequence_from_history,
    long_task_phase_for_agent_role,
    long_task_phase_for_workflow_node,
)
from adami_kernel.orchestrator.long_task_schema import LongTaskPhase
from adami_kernel.orchestrator.workflow_models import Node, WorkflowState


@pytest.fixture
def memory_db_path(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADAMI_L2_MEMORY_DB_PATH", str(tmp_path / "l2.db"))
    return tmp_path


@pytest.mark.asyncio
async def test_emit_phase_transition_history_bus_and_checkpoint(memory_db_path):
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
        reason="test",
        source_module="test",
        gate_detail="dag_route",
        history_extras={"completed_node_id": "n0", "next_node_id": "n1"},
    )
    assert st.context["current_phase"] == "code"
    assert any(
        h.get("event_type") == "phase_transition" and h.get("to_phase") == "code"
        for h in st.history
    )
    bus.publish.assert_awaited()
    call = bus.publish.await_args[0][0]
    assert isinstance(call, AdamiEvent)
    assert call.payload.get("event_type") == "PHASE_TRANSITION"
    assert call.payload.get("to_phase") == "code"
    assert call.payload.get("phase") == "code"
    assert call.payload.get("checkpoint_seq") == 1
    lg = await m.get_last_good_checkpoint(st.workflow_id)
    assert lg is not None and lg.get("phase") == "code"


@pytest.mark.asyncio
async def test_same_phase_skips_checkpoint_but_keeps_history(memory_db_path):
    m = LayeredMemory()
    await m.initialize(start_periodic_cleanup=False)
    bus = MagicMock()
    bus.publish = AsyncMock()
    st = WorkflowState(
        chat_id="c1",
        metadata={"long_task_tracking_enabled": True},
        context={"current_phase": "code"},
        nodes={"__start__": Node(node_id="__start__", node_type="START")},
        edges={"__start__": []},
    )
    await emit_phase_transition_if_changed(
        st,
        m,
        bus,
        to_phase=LongTaskPhase.CODE,
        reason="second_llm",
        source_module="test",
        gate_detail="dag_route",
    )
    assert len([h for h in st.history if h.get("event_type") == "phase_transition"]) == 1
    bus.publish.assert_awaited()


def test_extract_phase_sequence_from_history():
    hist = [
        {
            "event_type": "phase_transition",
            "at": "t1",
            "from_phase": "research",
            "to_phase": "code",
            "gate_detail": "dag_route",
        },
        {"foo": "bar"},
        {
            "event_type": "phase_transition",
            "at": "t2",
            "from_phase": "code",
            "to_phase": "test",
            "gate_detail": "dag_route",
        },
    ]
    seq = extract_phase_sequence_from_history(hist)
    assert len(seq) == 2
    assert seq[0]["to_phase"] == "code" and seq[1]["to_phase"] == "test"


def test_map_node_and_role():
    assert (
        long_task_phase_for_workflow_node(Node(node_id="x", node_type="TOOL")) == LongTaskPhase.TEST
    )
    assert (
        long_task_phase_for_workflow_node(Node(node_id="df", node_type="DELEGATE_DEERFLOW"))
        == LongTaskPhase.RESEARCH
    )
    assert long_task_phase_for_agent_role("engineer") == LongTaskPhase.CODE


@pytest.mark.asyncio
async def test_tracking_disabled_no_op(memory_db_path, monkeypatch):
    # 模块四默认开启：直接 stub 判定函数，避免 reload_settings 替换全局 settings 后 setattr 失效。
    monkeypatch.setattr(
        "adami_kernel.orchestrator.long_task_phase_gate.is_long_task_tracking_enabled",
        lambda state: False,
    )
    m = LayeredMemory()
    await m.initialize(start_periodic_cleanup=False)
    bus = MagicMock()
    bus.publish = AsyncMock()
    st = WorkflowState(
        chat_id="c1",
        nodes={"__start__": Node(node_id="__start__", node_type="START")},
        edges={"__start__": []},
    )
    await emit_phase_transition_if_changed(
        st,
        m,
        bus,
        to_phase=LongTaskPhase.DELIVER,
        reason="x",
        source_module="test",
        gate_detail="workflow_terminal",
    )
    assert not st.history
    bus.publish.assert_not_awaited()
