"""模块四步骤 1：长任务阶段与 StageArtifact 契约（Pydantic + WorkflowState 往返）。"""

import json
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from adami_kernel.orchestrator.long_task_schema import (
    LONG_TASK_CONTEXT_CURRENT_PHASE_KEY,
    LONG_TASK_CONTEXT_STAGES_KEY,
    LONG_TASK_METADATA_TRACKING_FLAG,
    LongTaskPhase,
    StageArtifact,
    append_stage_artifact,
    get_long_task_phase_view,
    maybe_initialize_long_task_context,
    parse_stage_artifacts_from_context,
    sha256_hex_of_utf8,
)
from adami_kernel.orchestrator.workflow_models import Node, WorkflowState


def _minimal_state(*, tracking: bool) -> WorkflowState:
    st = WorkflowState(
        chat_id="chat_test_lt",
        context={"original_task": "long horizon task"},
        nodes={"__start__": Node(node_id="__start__", node_type="START", description="入口")},
        edges={"__start__": []},
    )
    if tracking:
        st.metadata[LONG_TASK_METADATA_TRACKING_FLAG] = True
    return st


def test_initialize_and_three_phases_roundtrip():
    state = _minimal_state(tracking=True)
    maybe_initialize_long_task_context(state)

    assert state.context[LONG_TASK_CONTEXT_CURRENT_PHASE_KEY] == LongTaskPhase.RESEARCH.value
    assert state.context[LONG_TASK_CONTEXT_STAGES_KEY] == []
    assert state.metadata.get("long_task_schema_version") == 1

    artifacts = [
        StageArtifact(
            phase=LongTaskPhase.RESEARCH,
            artifact_type="research_summary",
            uri_or_payload_ref="file://.adami_data/artifacts/wf1/research.md",
            summary="Key findings (short).",
            producer_agent="Researcher",
            content_hash=sha256_hex_of_utf8("full doc body would live on disk"),
        ),
        StageArtifact(
            phase=LongTaskPhase.CODE,
            artifact_type="patch_bundle",
            uri_or_payload_ref="file://.adami_data/artifacts/wf1/diff.patch",
            summary="Implements feature X.",
            producer_agent="Engineer",
        ),
        StageArtifact(
            phase=LongTaskPhase.TEST,
            artifact_type="test_report",
            uri_or_payload_ref=None,
            summary="pytest: 12 passed",
            producer_agent="Tester",
        ),
    ]
    for a in artifacts:
        append_stage_artifact(state, a)

    phase, parsed = get_long_task_phase_view(state)
    assert phase == LongTaskPhase.TEST.value
    assert len(parsed) == 3
    assert parsed[0].artifact_type == "research_summary"
    assert parsed[1].phase == LongTaskPhase.CODE.value

    dumped = json.loads(state.model_dump_json())
    restored = WorkflowState.model_validate(dumped)
    r_phase, r_parsed = get_long_task_phase_view(restored)
    assert r_phase == LongTaskPhase.TEST.value
    assert len(r_parsed) == 3
    assert r_parsed[2].summary == "pytest: 12 passed"


def test_workflow_state_json_roundtrip_preserves_datetime_iso():
    state = _minimal_state(tracking=True)
    maybe_initialize_long_task_context(state)
    fixed = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)
    append_stage_artifact(
        state,
        StageArtifact(
            phase=LongTaskPhase.DELIVER,
            artifact_type="handoff",
            summary="done",
            producer_agent="Orchestrator",
            created_at=fixed,
        ),
    )
    restored = WorkflowState.model_validate(json.loads(state.model_dump_json()))
    stages = parse_stage_artifacts_from_context(restored.context)
    assert stages[0].created_at == fixed


def test_summary_length_guard_no_huge_blob_in_field():
    big = "x" * 9000
    with pytest.raises(ValidationError):
        StageArtifact(
            phase=LongTaskPhase.CODE,
            artifact_type="blob",
            summary=big,
            uri_or_payload_ref="file://.adami_data/out.bin",
            producer_agent="x",
        )


def test_uri_length_guard():
    long_uri = "s3://b/" + ("k" * 3000)
    with pytest.raises(ValidationError):
        StageArtifact(
            phase=LongTaskPhase.RESEARCH,
            artifact_type="ref",
            uri_or_payload_ref=long_uri,
            summary="ok",
            producer_agent="x",
        )


def test_tracking_off_leaves_context_untouched(monkeypatch):
    # 模块四默认开启：本用例显式关全局开关以验证“tracking=False 不改写 context”
    from adami_kernel.config import reload_settings

    monkeypatch.setenv("ADAMI_LONG_TASK_TRACKING_ENABLED", "false")
    reload_settings()
    state = _minimal_state(tracking=False)
    ctx_before = dict(state.context)
    maybe_initialize_long_task_context(state)
    assert state.context == ctx_before
