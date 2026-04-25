"""
模块四 · 步骤 6 / 6.1 验收（DeerFlow 侧车桥 + 工作流注册闸）

验收方案（与实现对照）：

1. 默认关：`ADAMI_DEERFLOW_ENABLED=false` 时不加载 DeerFlow 包、不发起侧车调用；含 `DELEGATE_DEERFLOW`
   的 DAG 在 `prepare_composed_workflow_for_bus` 被拒绝并抛出明确错误（与「未启用勿注册该节点」一致）。
2. 编排：`ADAMI_DEERFLOW_ENABLED=true` 时 `WorkflowEngine._execute_node` 执行 `DELEGATE_DEERFLOW`：
   提交 → 轮询 → 拉回结果；`context[node_id]` 含 `task_id` 与 `deerflow_result`；长任务跟踪开启时
   `long_task_stages` 可解析 `artifact_type=deerflow_delegate`（本文件用 FakeBridge 串联，无真实 DeerFlow 进程）。
3. 桥接契约：`integration/deer_flow_bridge.py` 提供 HTTP 与 CLI 两种后端；`stage_artifact_for_deerflow_delegate`
   将 JSON 结果映射为 `StageArtifact`（细测见 `tests/test_deer_flow_bridge.py`）。
4. 步骤 6.1 安全：`validate_deerflow_base_url` 拒绝 `0.0.0.0` 等全网绑定 host（可配置）；
   `ADAMI_DEERFLOW_ALLOWED_HOSTS` 白名单；`ADAMI_DEERFLOW_REQUIRE_TOKEN` 且无 token 时 HTTP 路径拒绝；
   HTTPS / 回环 HTTP 策略可测。
5. 阶段闸：`DELEGATE_DEERFLOW` 映射为 `LongTaskPhase.RESEARCH`（`tests/test_long_task_phase_gate.py`）。

未纳入本次自动化验收：与真实 DeerFlow 部署的 REST 路径完全一致（依赖运维配置路径模板）；
生产 mTLS 文件存在性需在目标环境手测。

细粒度用例见 `tests/test_deer_flow_bridge.py`；本文件提供 compose 闸 + 引擎串联验收。
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from adami_kernel.config import settings
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.integration import deer_flow_bridge as df
from adami_kernel.orchestrator.long_task_schema import parse_stage_artifacts_from_context
from adami_kernel.orchestrator.workflow_engine import WorkflowEngine
from adami_kernel.orchestrator.workflow_models import Node, WorkflowState


@pytest.mark.asyncio
async def test_step6_prepare_rejects_delegate_when_disabled(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADAMI_L2_MEMORY_DB_PATH", str(tmp_path / "s6.db"))
    monkeypatch.setattr(settings, "ADAMI_DEERFLOW_ENABLED", False)
    m = LayeredMemory()
    await m.initialize(start_periodic_cleanup=False)
    bus = MagicMock()
    bus.publish = AsyncMock()
    eng = WorkflowEngine(bus, m, MagicMock())
    st = WorkflowState(
        chat_id="c6",
        nodes={
            "d": Node(
                node_id="d",
                node_type="DELEGATE_DEERFLOW",
                config={"prompt": "x"},
            ),
        },
        edges={"d": []},
    )
    with pytest.raises(RuntimeError, match="ADAMI_DEERFLOW_ENABLED"):
        await eng.prepare_composed_workflow_for_bus(st)


@pytest.mark.asyncio
async def test_step6_acceptance_engine_executes_delegate(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADAMI_L2_MEMORY_DB_PATH", str(tmp_path / "s6b.db"))
    monkeypatch.setattr(settings, "ADAMI_DEERFLOW_ENABLED", True)
    monkeypatch.setattr(settings, "ADAMI_LONG_TASK_TRACKING_ENABLED", True)

    class FB:
        def __init__(self, http_client=None):
            pass

        async def submit(self, **kw):
            return "acc-task"

        async def run_until_done(self, task_id, poll_timeout_sec):
            return {"summary": "acceptance", "artifacts": []}

    monkeypatch.setattr(df, "DeerFlowBridge", FB)

    m = LayeredMemory()
    await m.initialize(start_periodic_cleanup=False)
    bus = MagicMock()
    bus.publish = AsyncMock()
    eng = WorkflowEngine(bus, m, MagicMock())

    st = WorkflowState(
        chat_id="c6b",
        workflow_id="wf_step6_acc",
        status="RUNNING",
        metadata={"long_task_tracking_enabled": True},
        nodes={
            "d1": Node(
                node_id="d1",
                node_type="DELEGATE_DEERFLOW",
                config={"prompt": "delegate prompt"},
                timeout=120,
            ),
        },
        edges={"d1": []},
        current_node_id="d1",
        context={},
    )
    from adami_kernel.orchestrator.long_task_schema import maybe_initialize_long_task_context

    maybe_initialize_long_task_context(st)

    await eng._execute_node(st)

    assert st.context["d1"]["task_id"] == "acc-task"
    arts = parse_stage_artifacts_from_context(st.context)
    assert any(a.artifact_type == "deerflow_delegate" for a in arts)
