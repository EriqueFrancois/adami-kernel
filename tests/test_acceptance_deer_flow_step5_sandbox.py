"""
模块四 · 步骤 5 验收（隔离沙箱 + StageArtifact + WorkflowEngine TOOL 路径）

验收方案（与实现对照）：

1. 契约：`SandboxRunHandle` 含 run_id、artifacts_dir、log_path、exit_code；`stage_artifact_for_sandbox_run`
   生成 `StageArtifact`（artifact_type=sandbox_run，uri_or_payload_ref 为 file:// 产物目录）。
2. 安全：`validate_path_segment` / `safe_run_directory` 拒绝 `..`、斜杠等路径穿越式片段（单测
   `tests/test_long_task_sandbox.py`）。
3. 执行：`run_isolated_tool_command` 在 `path_long_task_runs_dir/{workflow_id}/{run_id}/` 下 cwd 执行；
   长任务代码阶段产物落在该目录，可被 workflow 黑板引用而非污染内核 cwd。
4. 编排：`WorkflowEngine._execute_node` 在「长任务跟踪开启 + ADAMI_LONG_TASK_ISOLATED_TOOL_RUN +
   未设置 long_task_disable_isolated_run」时对 TOOL 走隔离路径，并向 `long_task_stages` 追加产物；
   命令含 `pytest`（大小写不敏感）时产物阶段为 `test`，否则 `code`。
5. 回退：节点 `long_task_disable_isolated_run: True` 时走 `ToolboxManager.execute_command`（不追加 sandbox_run
   产物；与既有 .adami_sandbox 行为一致方向）。

细粒度用例见 `tests/test_long_task_sandbox.py`；本文件提供 WorkflowEngine 串联验收。
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from adami_kernel.config import settings
from adami_kernel.cortex.tools_manager import ToolboxManager
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.orchestrator.long_task_schema import (
    maybe_initialize_long_task_context,
    parse_stage_artifacts_from_context,
)
from adami_kernel.orchestrator.workflow_engine import WorkflowEngine
from adami_kernel.orchestrator.workflow_models import Node, WorkflowState


@pytest.mark.asyncio
async def test_step5_acceptance_workflow_engine_tool_writes_artifact_under_run_dir(
    tmp_path, monkeypatch
):
    """长任务 TOOL 经引擎执行：隔离目录落盘 + long_task_stages 可解析 sandbox_run。"""
    monkeypatch.setattr(settings, "ADAMI_L2_MEMORY_DB_PATH", str(tmp_path / "acc5.db"))
    monkeypatch.setattr(settings, "ADAMI_LONG_TASK_RUNS_DIR", str(tmp_path / "ltr_acc5"))
    monkeypatch.setattr(settings, "ADAMI_LONG_TASK_ISOLATED_TOOL_RUN", True)

    mem = LayeredMemory()
    await mem.initialize(start_periodic_cleanup=False)
    bus = MagicMock()
    bus.publish = AsyncMock()

    tb_dir = tmp_path / "tb_sbx"
    tb = ToolboxManager(sandbox_dir=str(tb_dir))
    await tb.initialize_environment()

    eng = WorkflowEngine(bus, mem, tb)
    wf_id = "wf_acc_step5"
    st = WorkflowState(
        workflow_id=wf_id,
        chat_id="c_acc5",
        status="RUNNING",
        metadata={"long_task_tracking_enabled": True},
        nodes={
            "t1": Node(
                node_id="t1",
                node_type="TOOL",
                config={
                    "command": """python -c "open('wf_marker.txt','w').write('step5_ok')" """,
                },
                timeout=120,
            ),
        },
        edges={"t1": []},
        current_node_id="t1",
        context={},
    )
    maybe_initialize_long_task_context(st)

    await eng._execute_node(st)

    arts = parse_stage_artifacts_from_context(st.context)
    assert len(arts) >= 1
    last = arts[-1]
    assert last.artifact_type == "sandbox_run"
    assert last.uri_or_payload_ref.startswith("file://")
    run_root = Path(last.uri_or_payload_ref.replace("file://", ""))
    # as_uri may be file:/// (three slashes) on POSIX
    if not run_root.exists():
        run_root = Path(last.uri_or_payload_ref[7:])  # strip file://
    assert (run_root / "wf_marker.txt").read_text() == "step5_ok"
    assert str(last.phase) == "code"


@pytest.mark.asyncio
async def test_step5_acceptance_pytest_command_sets_test_phase_on_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADAMI_L2_MEMORY_DB_PATH", str(tmp_path / "acc5b.db"))
    monkeypatch.setattr(settings, "ADAMI_LONG_TASK_RUNS_DIR", str(tmp_path / "ltr_acc5b"))
    monkeypatch.setattr(settings, "ADAMI_LONG_TASK_ISOLATED_TOOL_RUN", True)

    mem = LayeredMemory()
    await mem.initialize(start_periodic_cleanup=False)
    bus = MagicMock()
    bus.publish = AsyncMock()

    tb = ToolboxManager(sandbox_dir=str(tmp_path / "tb2"))
    await tb.initialize_environment()
    eng = WorkflowEngine(bus, mem, tb)

    st = WorkflowState(
        workflow_id="wf_acc5b",
        chat_id="c5b",
        status="RUNNING",
        metadata={"long_task_tracking_enabled": True},
        nodes={
            "t2": Node(
                node_id="t2",
                node_type="TOOL",
                config={"command": 'python -c "pass"'},
                timeout=120,
            ),
        },
        edges={"t2": []},
        current_node_id="t2",
        context={},
    )
    maybe_initialize_long_task_context(st)
    # 子进程非 shell：用 python -c 执行；字符串含 pytest 以匹配引擎内 "pytest" in cmd.lower()
    st.nodes["t2"].config["command"] = "python -c \"_='pytest'\""

    await eng._execute_node(st)

    arts = parse_stage_artifacts_from_context(st.context)
    assert arts[-1].artifact_type == "sandbox_run"
    assert str(arts[-1].phase) == "test"


@pytest.mark.asyncio
async def test_step5_acceptance_disable_isolated_uses_execute_command(tmp_path, monkeypatch):
    """long_task_disable_isolated_run 时不得追加 sandbox_run 产物。"""
    monkeypatch.setattr(settings, "ADAMI_L2_MEMORY_DB_PATH", str(tmp_path / "acc5c.db"))
    monkeypatch.setattr(settings, "ADAMI_LONG_TASK_ISOLATED_TOOL_RUN", True)

    mem = LayeredMemory()
    await mem.initialize(start_periodic_cleanup=False)
    bus = MagicMock()
    bus.publish = AsyncMock()

    tb = MagicMock()
    tb.execute_command = AsyncMock(return_value={"exit_code": 0, "stdout": "ok", "stderr": ""})
    tb._get_venv_env = MagicMock(return_value={})

    eng = WorkflowEngine(bus, mem, tb)
    st = WorkflowState(
        workflow_id="wf_acc5c",
        chat_id="c5c",
        status="RUNNING",
        metadata={"long_task_tracking_enabled": True},
        nodes={
            "t3": Node(
                node_id="t3",
                node_type="TOOL",
                config={
                    "command": "echo hi",
                    "long_task_disable_isolated_run": True,
                },
            ),
        },
        edges={"t3": []},
        current_node_id="t3",
        context={},
    )
    maybe_initialize_long_task_context(st)

    await eng._execute_node(st)

    tb.execute_command.assert_awaited_once()
    arts = parse_stage_artifacts_from_context(st.context)
    assert not any(a.artifact_type == "sandbox_run" for a in arts)
