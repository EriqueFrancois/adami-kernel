"""模块四步骤 5：隔离子进程沙箱与 StageArtifact 引用。"""

from pathlib import Path

import pytest

from adami_kernel.config import settings
from adami_kernel.cortex.tools_manager import ToolboxManager
from adami_kernel.orchestrator.long_task_sandbox import (
    artifacts_dir_uri,
    run_isolated_tool_command,
    safe_run_directory,
    stage_artifact_for_sandbox_run,
    validate_path_segment,
)
from adami_kernel.orchestrator.long_task_schema import parse_stage_artifacts_from_context
from adami_kernel.orchestrator.workflow_models import WorkflowState


def test_validate_path_segment_rejects_traversal_like():
    with pytest.raises(ValueError):
        validate_path_segment("../etc", "x")
    with pytest.raises(ValueError):
        validate_path_segment("a/b", "x")


def test_safe_run_directory_confined(tmp_path):
    root = str(tmp_path / "r")
    d = safe_run_directory(root, "wf_abc", "run1")
    assert d.startswith(str(tmp_path))


def test_artifacts_dir_uri_is_file_scheme(tmp_path):
    u = artifacts_dir_uri(str(tmp_path / "sub"))
    assert u.startswith("file://")


@pytest.mark.asyncio
async def test_isolated_run_creates_output_and_stage_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADAMI_LONG_TASK_RUNS_DIR", str(tmp_path / "ltr"))
    tb = ToolboxManager(sandbox_dir=str(tmp_path / "adami_sbx"))
    await tb.initialize_environment()
    res, h = await run_isolated_tool_command(
        tb,
        "python -c \"open('out.txt','w').write('ok')\"",
        workflow_id="wf_iso_1",
        timeout=60.0,
    )
    assert res["exit_code"] == 0
    assert (Path(h.artifacts_dir) / "out.txt").read_text() == "ok"
    assert Path(h.log_path).is_file()
    art = stage_artifact_for_sandbox_run(h, command="python -c ...", set_phase_test=False)
    st = WorkflowState(
        chat_id="c",
        metadata={"long_task_tracking_enabled": True},
        context={"long_task_stages": []},
    )
    st.context["long_task_stages"].append(art.model_dump(mode="json"))
    parsed = parse_stage_artifacts_from_context(st.context)
    assert len(parsed) == 1
    assert parsed[0].artifact_type == "sandbox_run"
    assert parsed[0].uri_or_payload_ref.startswith("file://")


@pytest.mark.asyncio
async def test_pytest_command_maps_test_phase(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ADAMI_LONG_TASK_RUNS_DIR", str(tmp_path / "ltr2"))
    tb = ToolboxManager(sandbox_dir=str(tmp_path / "s2"))
    await tb.initialize_environment()
    _, h = await run_isolated_tool_command(
        tb,
        'python -c "print(1)"',
        workflow_id="wf_t",
        timeout=30.0,
    )
    art_code = stage_artifact_for_sandbox_run(h, command="echo", set_phase_test=False)
    art_test = stage_artifact_for_sandbox_run(h, command="pytest -q", set_phase_test=True)
    assert str(art_code.phase) == "code"
    assert str(art_test.phase) == "test"
