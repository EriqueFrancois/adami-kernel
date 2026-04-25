"""
模块四 · 步骤 3 验收（WorkflowEngine / MultiAgent 阶段闸）

验收方案（与实现对照）：

1. 结构化 history：`WorkflowState.history` 中出现 `event_type == "phase_transition"`，
   含 `from_phase`、`to_phase`、`gate_detail`、`source_module`、`workflow_version` 等，
   可用 `extract_phase_sequence_from_history` 还原阶段序列（供离线回放与断言）。
2. 总线可观测：`workflow.events` 上发布的事件 `payload["event_type"] == "PHASE_TRANSITION"`，
   且携带 `workflow_id`、`chat_id`、`from_phase`、`to_phase`、`gate_detail`（与 Sim NDJSON 轨迹兼容，
   具体字段在 `payload_redacted` 内依 trace 中间件脱敏规则保留）。
3. context：`context["current_phase"]` 与最后一次阶段闸的 `to_phase` 一致。
4. checkpoint 协同：阶段变化或 `workflow_terminal` / HITL 边界时，`LayeredMemory` 中 `last_good`
   与阶段 checkpoint 可读取；同阶段连续闸（如两个 CODE 节点）允许无新 checkpoint（实现为 if_changed）。
5. HITL 边界：`pre_hitl_pause` 写入 checkpoint 且 `update_last_good=False`；
   `post_hitl_resume` 写入且 `update_last_good=True`；暂停前后 `current_phase` 字符串可保持一致。
6. 代码接线（人工/回归）：`workflow_engine._route_next`、高危暂停前、`resume_workflow`；
   `multi_agent_orchestrator` 角色切换与 PAUSED/ resume —— 由仓库静态审查与本文件 + `tests/test_long_task_phase_gate.py` 覆盖核心闸逻辑。

细粒度单测见 `tests/test_long_task_phase_gate.py`；本文件提供串联验收。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from adami_kernel.config import settings
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.nexus.event import AdamiEvent
from adami_kernel.orchestrator.long_task_phase_gate import (
    checkpoint_hitl_boundary,
    emit_phase_transition_if_changed,
    extract_phase_sequence_from_history,
)
from adami_kernel.orchestrator.long_task_schema import LongTaskPhase
from adami_kernel.orchestrator.workflow_models import Node, WorkflowState


@pytest.mark.asyncio
async def test_step3_acceptance_integrated_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADAMI_L2_MEMORY_DB_PATH", str(tmp_path / "l2.db"))
    m = LayeredMemory()
    await m.initialize(start_periodic_cleanup=False)
    bus = MagicMock()
    bus.publish = AsyncMock()

    st = WorkflowState(
        chat_id="chat_acc_s3",
        metadata={"long_task_tracking_enabled": True},
        nodes={"__start__": Node(node_id="__start__", node_type="START")},
        edges={"__start__": []},
    )
    wf = st.workflow_id

    # 模拟 DAG 推进：research（初始化）→ code → test → deliver
    await emit_phase_transition_if_changed(
        st,
        m,
        bus,
        to_phase=LongTaskPhase.CODE,
        reason="route_n1",
        source_module="workflow.engine",
        gate_detail="dag_route",
        history_extras={"completed_node_id": "__start__", "next_node_id": "n_llm"},
    )
    await emit_phase_transition_if_changed(
        st,
        m,
        bus,
        to_phase=LongTaskPhase.TEST,
        reason="route_n2",
        source_module="workflow.engine",
        gate_detail="dag_route",
        history_extras={"completed_node_id": "n_llm", "next_node_id": "n_tool"},
    )
    await emit_phase_transition_if_changed(
        st,
        m,
        bus,
        to_phase=LongTaskPhase.DELIVER,
        reason="done",
        source_module="workflow.engine",
        gate_detail="workflow_terminal",
        history_extras={"completed_node_id": "n_tool"},
    )

    seq = extract_phase_sequence_from_history(st.history)
    assert [x["to_phase"] for x in seq] == ["code", "test", "deliver"]
    assert st.context["current_phase"] == "deliver"

    assert bus.publish.await_count >= 3
    for call in bus.publish.await_args_list:
        ev: AdamiEvent = call[0][0]
        assert ev.target_topic == "workflow.events"
        assert ev.payload.get("event_type") == "PHASE_TRANSITION"
        assert ev.payload.get("workflow_id") == wf
        assert ev.payload.get("chat_id") == "chat_acc_s3"

    lg = await m.get_last_good_checkpoint(wf)
    assert lg is not None
    assert lg.get("phase") == "deliver"

    # HITL：pre 不推进 last_good 语义上的“最后成功阶段产物”指针；post 推进
    st2 = WorkflowState(
        chat_id="chat_hitl",
        metadata={"long_task_tracking_enabled": True},
        nodes={"__start__": Node(node_id="__start__", node_type="START")},
        edges={"__start__": []},
    )
    wf2 = st2.workflow_id
    # 首次 research→code 会写 checkpoint；若上下文已是 code 再 emit→code 则不会写 last_good
    await emit_phase_transition_if_changed(
        st2,
        m,
        bus,
        to_phase=LongTaskPhase.CODE,
        reason="seed",
        source_module="test",
        gate_detail="dag_route",
    )
    lg_before = await m.get_last_good_checkpoint(wf2)
    assert lg_before is not None

    await checkpoint_hitl_boundary(
        st2,
        m,
        bus,
        kind="pre_hitl_pause",
        node_id="n_x",
        reason="need_human",
        source_module="workflow.engine",
    )
    lg_mid = await m.get_last_good_checkpoint(wf2)
    assert lg_mid == lg_before

    await checkpoint_hitl_boundary(
        st2,
        m,
        bus,
        kind="post_hitl_resume",
        reason="approved",
        source_module="workflow.engine",
    )
    lg_after = await m.get_last_good_checkpoint(wf2)
    assert lg_after is not None
    assert lg_after.get("phase") == "code"
    hitl_hist = [
        h for h in st2.history if h.get("gate_detail") in ("pre_hitl_pause", "post_hitl_resume")
    ]
    assert len(hitl_hist) == 2
