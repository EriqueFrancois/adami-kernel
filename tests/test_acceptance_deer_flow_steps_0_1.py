"""
模块四（DeerFlow 对齐）步骤 0–1 验收：文档与交叉引用 + 与 LayeredMemory 同构的 JSON 往返。

步骤 0：边界文档存在；README / tasklist 引用一致；正文含评审必过条款关键词。
步骤 1：long_task_schema 行为与 workflow 状态 JSON 契约（与 hippocampus 持久化路径一致）。
"""

from pathlib import Path

import pytest

from adami_kernel.orchestrator.long_task_schema import (
    LongTaskPhase,
    StageArtifact,
    append_stage_artifact,
    maybe_initialize_long_task_context,
)
from adami_kernel.orchestrator.workflow_models import Node, WorkflowState


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@pytest.mark.parametrize(
    "keyword",
    [
        "单一真源",
        "双运行时",
        "checkpoint",
        "沙箱",
        "档位 A",
        "档位 B",
        "档位 C",
    ],
)
def test_step0_boundary_doc_contains_review_keywords(keyword: str):
    doc = _repo_root() / "docs" / "deer_flow_alignment_and_boundary.md"
    assert doc.is_file(), "步骤 0 边界文档应存在"
    text = doc.read_text(encoding="utf-8")
    assert keyword in text, f"文档应包含评审关键词: {keyword!r}"


def test_step0_readme_and_tasklist_link_boundary_doc():
    root = _repo_root()
    path_fragment = "docs/deer_flow_alignment_and_boundary.md"
    readme = (root / "README.md").read_text(encoding="utf-8")
    tasklist = (root / "tasklist.md").read_text(encoding="utf-8")
    assert path_fragment in readme
    assert path_fragment in tasklist


def test_step1_workflow_json_matches_layered_memory_shape():
    """与 layered_memory.save_workflow_state 一致：model_dump_json → json.loads → model_validate。"""
    import json

    state = WorkflowState(
        chat_id="acc_lt",
        metadata={"long_task_tracking_enabled": True},
        nodes={"__start__": Node(node_id="__start__", node_type="START")},
        edges={"__start__": []},
    )
    maybe_initialize_long_task_context(state)
    append_stage_artifact(
        state,
        StageArtifact(
            phase=LongTaskPhase.RESEARCH,
            artifact_type="smoke",
            summary="acc",
            uri_or_payload_ref="file://.adami_data/x",
            producer_agent="acceptance",
        ),
    )
    blob = state.model_dump_json()
    restored = WorkflowState.model_validate(json.loads(blob))
    assert restored.context.get("current_phase") == LongTaskPhase.RESEARCH.value
    assert isinstance(restored.context.get("long_task_stages"), list)
    assert len(restored.context["long_task_stages"]) == 1
    assert restored.context["long_task_stages"][0]["artifact_type"] == "smoke"
