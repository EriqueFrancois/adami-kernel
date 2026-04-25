"""
模块四 · 步骤 4 / 4.1 验收（失败恢复、重试与 HITL 重放）

验收方案（与实现对照）：

1. 失败分类：`classify_workflow_node_failure` 将错误串映射为 transient / phase_fatal；
   配置项 `ADAMI_LONG_TASK_PHASE_FATAL_SUBSTRINGS`、`ADAMI_LONG_TASK_TRANSIENT_SUBSTRINGS` 可调整。
2. transient：`WorkflowEngine._handle_node_failure` 递增 `error_retry_counts[node_id]`，
   在 `<= max_retries` 时调度同节点重试，并在 `history` 写入 `workflow_node_failure` + `recovery_action=retry_scheduled`；
   超过上限后 `status=FAILED` 且 `recovery_action=failed_terminal`。
3. phase_fatal：写入 `record_checkpoint_failure`；在 `phase_recovery_count < ADAMI_WORKFLOW_PHASE_RECOVERY_MAX`
   且存在可解析的 last_good checkpoint 时，执行 `rollback_to_last_good_checkpoint`，
   递增 `metadata.phase_recovery_count`，清零该节点重试，保持 RUNNING 并再次执行节点；
   否则 `FAILED` 且审计 `failed_terminal` / `rollback_exhausted_or_missing_checkpoint`。
4. 审计：`WorkflowState.history` 中 `event_type=workflow_node_failure` 可追溯失败类与恢复动作。
5. 步骤 4.1：`apply_replay_from_phase_checkpoint` 与 `resume_workflow(..., resume_mode=replay_from_phase, replay_phase=...)`
   设置 `long_task_redo_marker`、`checkpoint_replay_{phase}`，并追加 `hitl_replay_from_phase`。
6. HITL：`HitlHandler.process_resume(..., action="replay", user_input={"replay_phase": ...})` 走上述 replay 路径。
7. 状态加载：`LayeredMemory.get_workflow_state_by_workflow_id` 支持仅 workflow_id 的 pause/resume/cancel。

细粒度用例见 `tests/test_long_task_failure_recovery.py`；本文件提供一条串联验收。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from adami_kernel.config import settings
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.orchestrator.hitl_handler import HitlHandler
from adami_kernel.orchestrator.long_task_failure_policy import classify_workflow_node_failure
from adami_kernel.orchestrator.workflow_engine import WorkflowEngine
from adami_kernel.orchestrator.workflow_models import Node, WorkflowState


@pytest.mark.asyncio
async def test_step4_acceptance_integrated_flow(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADAMI_L2_MEMORY_DB_PATH", str(tmp_path / "acc4.db"))
    m = LayeredMemory()
    await m.initialize(start_periodic_cleanup=False)
    bus = MagicMock()
    bus.publish = AsyncMock()

    # --- 1) 分类 ---
    n_tool = Node(node_id="t", node_type="TOOL", config={})
    assert classify_workflow_node_failure(n_tool, "403 Forbidden") == "phase_fatal"
    assert classify_workflow_node_failure(n_tool, "Read timed out") == "transient"

    eng = WorkflowEngine(bus, m, MagicMock())
    eng._execute_node = AsyncMock()
    wf = "wf_acc_step4"
    st = WorkflowState(
        workflow_id=wf,
        chat_id="c_acc",
        metadata={"long_task_tracking_enabled": True},
        nodes={
            "n1": Node(node_id="n1", node_type="TOOL", max_retries=1),
            "__start__": Node(node_id="__start__", node_type="START"),
        },
        edges={"n1": []},
        current_node_id="n1",
        status="RUNNING",
        context={"current_phase": "test"},
    )
    await m.save_workflow_phase_checkpoint(
        wf,
        "code",
        {"summary": "stable_point", "v": 1},
        workflow_state_version=5,
        update_last_good=True,
    )

    # --- 2) phase_fatal → 回滚 + 审计 + 再调度 ---
    await eng._handle_node_failure(st, "n1", "HTTP 401 Unauthorized")
    audits = [h for h in st.history if h.get("event_type") == "workflow_node_failure"]
    assert any(a.get("failure_class") == "phase_fatal" for a in audits)
    assert st.metadata.get("phase_recovery_count") == 1
    assert st.context.get("current_phase") == "code"
    assert st.context.get("phase_recovery_payload", {}).get("summary") == "stable_point"
    assert st.status == "RUNNING"
    assert eng._execute_node.call_count >= 1

    # --- 3) 持久化后仅 workflow_id 可读（HITL 路径）---
    await m.save_workflow_state(st)
    st_reload = await m.get_workflow_state_by_workflow_id(wf)
    assert st_reload is not None
    assert st_reload.chat_id == "c_acc"

    # --- 4) replay_from_phase（4.1）---
    st_reload.status = "PAUSED"
    await m.save_workflow_state(st_reload)
    await eng.resume_workflow(
        wf,
        user_input={
            "resume_mode": "replay_from_phase",
            "replay_phase": "code",
        },
    )
    final = await m.get_workflow_state_by_workflow_id(wf)
    assert final is not None
    assert final.status == "RUNNING"
    assert final.context.get("long_task_redo_marker") is True
    assert any(h.get("event_type") == "hitl_replay_from_phase" for h in final.history)

    # --- 5) HitlHandler.process_resume replay 分支（workflow_engine 为 mock 时只测调用链）---
    eng2 = MagicMock()
    eng2.resume_workflow = AsyncMock()
    eng2.cancel_workflow = AsyncMock()
    hh = HitlHandler(bus, workflow_engine=eng2)
    hh.active_paused_workflows["wf_h"] = MagicMock()
    await hh.process_resume("wf_h", "replay", user_input={"replay_phase": "research"})
    eng2.resume_workflow.assert_awaited()
    call = eng2.resume_workflow.await_args
    assert call.args[0] == "wf_h"
    ui = call.kwargs.get("user_input") or (call.args[1] if len(call.args) > 1 else {})
    assert ui.get("resume_mode") == "replay_from_phase"
    assert ui.get("replay_phase") == "research"
