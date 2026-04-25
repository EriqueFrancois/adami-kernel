"""模块四步骤 4 / 4.1：失败分类、回滚、审计与 HITL replay_from_phase。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from adami_kernel.config import settings
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.orchestrator.long_task_failure_policy import classify_workflow_node_failure
from adami_kernel.orchestrator.long_task_recovery import (
    apply_replay_from_phase_checkpoint,
    rollback_to_last_good_checkpoint,
)
from adami_kernel.orchestrator.workflow_engine import WorkflowEngine
from adami_kernel.orchestrator.workflow_models import Node, WorkflowState


@pytest.fixture
def tmp_db(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "ADAMI_L2_MEMORY_DB_PATH", str(tmp_path / "f.db"))
    return tmp_path


def test_classify_fatal_vs_transient():
    n = Node(node_id="t", node_type="TOOL", config={})
    assert classify_workflow_node_failure(n, "HTTP 403 forbidden") == "phase_fatal"
    assert classify_workflow_node_failure(n, "connection timeout") == "transient"


@pytest.mark.asyncio
async def test_rollback_restores_checkpoint_payload(tmp_db):
    m = LayeredMemory()
    await m.initialize(start_periodic_cleanup=False)
    st = WorkflowState(
        chat_id="c",
        metadata={"long_task_tracking_enabled": True},
        nodes={"x": Node(node_id="x", node_type="TOOL")},
        edges={"x": []},
    )
    await m.save_workflow_phase_checkpoint(
        st.workflow_id,
        "code",
        {"summary": "stable", "k": 1},
        workflow_state_version=1,
        update_last_good=True,
    )
    ok = await rollback_to_last_good_checkpoint(st, m)
    assert ok
    assert st.context["current_phase"] == "code"
    assert st.context["phase_recovery_payload"]["summary"] == "stable"


@pytest.mark.asyncio
async def test_transient_retries_then_failed_with_audit(tmp_db):
    m = LayeredMemory()
    await m.initialize(start_periodic_cleanup=False)
    bus = MagicMock()
    bus.publish = AsyncMock()
    eng = WorkflowEngine(bus, m, MagicMock())
    eng._execute_node = AsyncMock()
    nid = "tool1"
    st = WorkflowState(
        chat_id="c",
        metadata={"long_task_tracking_enabled": False},
        nodes={
            nid: Node(node_id=nid, node_type="TOOL", max_retries=2),
            "__start__": Node(node_id="__start__", node_type="START"),
        },
        edges={nid: []},
        current_node_id=nid,
        status="RUNNING",
    )
    await eng._handle_node_failure(st, nid, "transient timeout")
    assert st.error_retry_counts[nid] == 1
    assert st.status == "RUNNING"
    await eng._handle_node_failure(st, nid, "transient timeout")
    assert st.error_retry_counts[nid] == 2
    await eng._handle_node_failure(st, nid, "transient timeout")
    assert st.status == "FAILED"
    audits = [h for h in st.history if h.get("event_type") == "workflow_node_failure"]
    assert any(a.get("recovery_action") == "failed_terminal" for a in audits)


@pytest.mark.asyncio
async def test_phase_fatal_rollback_then_retry(tmp_db):
    m = LayeredMemory()
    await m.initialize(start_periodic_cleanup=False)
    bus = MagicMock()
    bus.publish = AsyncMock()
    eng = WorkflowEngine(bus, m, MagicMock())
    eng._execute_node = AsyncMock()
    nid = "t1"
    st = WorkflowState(
        chat_id="c",
        metadata={"long_task_tracking_enabled": True},
        nodes={
            nid: Node(node_id=nid, node_type="TOOL", max_retries=1),
            "__start__": Node(node_id="__start__", node_type="START"),
        },
        edges={nid: []},
        current_node_id=nid,
        status="RUNNING",
        context={"current_phase": "test"},
    )
    await m.save_workflow_phase_checkpoint(
        st.workflow_id,
        "code",
        {"summary": "rollback_here"},
        workflow_state_version=3,
        update_last_good=True,
    )
    await eng._handle_node_failure(st, nid, "403 forbidden")
    assert st.metadata.get("phase_recovery_count") == 1
    assert st.context.get("current_phase") == "code"
    assert st.status == "RUNNING"
    assert st.error_retry_counts.get(nid, 0) == 0
    assert eng._execute_node.call_count >= 1


@pytest.mark.asyncio
async def test_phase_fatal_exhausted_to_failed(tmp_db, monkeypatch):
    monkeypatch.setattr(settings, "ADAMI_WORKFLOW_PHASE_RECOVERY_MAX", 0)
    m = LayeredMemory()
    await m.initialize(start_periodic_cleanup=False)
    bus = MagicMock()
    bus.publish = AsyncMock()
    eng = WorkflowEngine(bus, m, MagicMock())
    eng._execute_node = AsyncMock()
    nid = "t1"
    st = WorkflowState(
        chat_id="c",
        metadata={"long_task_tracking_enabled": True},
        nodes={nid: Node(node_id=nid, node_type="TOOL")},
        edges={nid: []},
        current_node_id=nid,
        status="RUNNING",
    )
    await m.save_workflow_phase_checkpoint(
        st.workflow_id,
        "code",
        {"x": 1},
        update_last_good=True,
    )
    await eng._handle_node_failure(st, nid, "401 unauthorized")
    assert st.status == "FAILED"
    assert any(
        h.get("recovery_action") == "failed_terminal"
        for h in st.history
        if h.get("event_type") == "workflow_node_failure"
    )


@pytest.mark.asyncio
async def test_replay_from_phase_sets_redo_marker(tmp_db):
    m = LayeredMemory()
    await m.initialize(start_periodic_cleanup=False)
    st = WorkflowState(
        chat_id="c",
        metadata={"long_task_tracking_enabled": True},
        nodes={"__start__": Node(node_id="__start__", node_type="START")},
        edges={"__start__": []},
    )
    await m.save_workflow_phase_checkpoint(
        st.workflow_id,
        "researcher",
        {"summary": "cached"},
        update_last_good=True,
    )
    ok = await apply_replay_from_phase_checkpoint(st, m, "researcher")
    assert ok
    assert st.context.get("long_task_redo_marker") is True
    assert "researcher" in (st.context.get("long_task_replay_phases") or [])
    assert any(h.get("event_type") == "hitl_replay_from_phase" for h in st.history)


@pytest.mark.asyncio
async def test_resume_workflow_replay_from_phase(tmp_db):
    m = LayeredMemory()
    await m.initialize(start_periodic_cleanup=False)
    bus = MagicMock()
    bus.publish = AsyncMock()
    eng = WorkflowEngine(bus, m, MagicMock())
    eng._execute_node = AsyncMock()
    wf = "wf_resume_r"
    st = WorkflowState(
        workflow_id=wf,
        chat_id="c",
        status="PAUSED",
        metadata={"long_task_tracking_enabled": True},
        nodes={"__start__": Node(node_id="__start__", node_type="START")},
        edges={"__start__": []},
    )
    await m.save_workflow_state(st)
    await m.save_workflow_phase_checkpoint(
        wf,
        "research",
        {"summary": "snap"},
        update_last_good=True,
    )
    await eng.resume_workflow(
        wf,
        user_input={
            "resume_mode": "replay_from_phase",
            "replay_phase": "research",
        },
    )
    reloaded = await m.get_workflow_state(wf, "c")
    assert reloaded is not None
    assert reloaded.status == "RUNNING"
    assert reloaded.context.get("long_task_redo_marker") is True
    assert reloaded.context.get("checkpoint_replay_research", {}).get("summary") == "snap"
