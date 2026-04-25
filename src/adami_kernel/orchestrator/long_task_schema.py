"""
长任务阶段与产物 Schema（模块四 · 步骤 1）

对标 DeerFlow 的上下文工程：黑板 `WorkflowState.context` 中以下键为受控槽位，
大内容经 uri_or_payload_ref 外置，summary 仅保留短摘要（长度由模型约束）。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from enum import Enum
from typing import Any, List, Optional, Tuple

from pydantic import BaseModel, ConfigDict, Field, field_validator

from adami_kernel.config import settings
from adami_kernel.i18n import t as i18n_t
from adami_kernel.orchestrator.workflow_models import WorkflowState


def _ltsc_t(key: str, **kwargs: Any) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


# --- 受控 context 键（编排层与各 Agent 应优先通过本模块 API 读写） ---

LONG_TASK_CONTEXT_STAGES_KEY = "long_task_stages"
LONG_TASK_CONTEXT_CURRENT_PHASE_KEY = "current_phase"

# metadata 键：与 workflow_models.WorkflowState.metadata 约定配合
LONG_TASK_METADATA_TRACKING_FLAG = "long_task_tracking_enabled"
LONG_TASK_METADATA_SCHEMA_VERSION_KEY = "long_task_schema_version"


class LongTaskPhase(str, Enum):
    """长任务生命周期阶段（研究→实现→验证→迭代→交付）。"""

    RESEARCH = "research"
    CODE = "code"
    TEST = "test"
    ITERATE = "iterate"
    DELIVER = "deliver"


class StageArtifact(BaseModel):
    """某一阶段结束时的结构化产物描述（可持久化进 WorkflowState.context）。"""

    model_config = ConfigDict(use_enum_values=True)

    phase: LongTaskPhase
    artifact_type: str = Field(
        ...,
        min_length=1,
        max_length=128,
        description=_ltsc_t("ltsc.field.artifact_type"),
    )
    uri_or_payload_ref: Optional[str] = Field(
        default=None,
        max_length=2048,
        description=_ltsc_t("ltsc.field.uri_ref"),
    )
    summary: str = Field(
        default="",
        max_length=8192,
        description=_ltsc_t("ltsc.field.summary"),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description=_ltsc_t("ltsc.field.created_at"),
    )
    producer_agent: str = Field(
        default="unknown",
        max_length=256,
        description=_ltsc_t("ltsc.field.producer"),
    )
    content_hash: Optional[str] = Field(
        default=None,
        max_length=128,
        description=_ltsc_t("ltsc.field.content_hash"),
    )

    @field_validator("artifact_type")
    @classmethod
    def _strip_artifact_type(cls, v: str) -> str:
        s = v.strip()
        if not s:
            raise ValueError("artifact_type must be non-empty")
        return s


def is_long_task_tracking_enabled(state: WorkflowState) -> bool:
    """全局配置或 per-workflow metadata 任一为真即开启阶段跟踪。"""
    from adami_kernel.config import settings as _settings

    if bool(state.metadata.get(LONG_TASK_METADATA_TRACKING_FLAG)):
        return True
    return bool(getattr(_settings, "ADAMI_LONG_TASK_TRACKING_ENABLED", False))


def maybe_initialize_long_task_context(state: WorkflowState) -> None:
    """
    在编排入口（如 prepare_composed_workflow_for_bus）调用：
    开启跟踪时写入 current_phase、空 stages 列表与 schema 版本；未开启则不改写 context。
    """
    if not is_long_task_tracking_enabled(state):
        return
    if LONG_TASK_CONTEXT_CURRENT_PHASE_KEY not in state.context:
        state.context[LONG_TASK_CONTEXT_CURRENT_PHASE_KEY] = LongTaskPhase.RESEARCH.value
    if LONG_TASK_CONTEXT_STAGES_KEY not in state.context:
        state.context[LONG_TASK_CONTEXT_STAGES_KEY] = []
    if LONG_TASK_METADATA_SCHEMA_VERSION_KEY not in state.metadata:
        state.metadata[LONG_TASK_METADATA_SCHEMA_VERSION_KEY] = 1


def append_stage_artifact(
    state: WorkflowState,
    artifact: StageArtifact,
    *,
    set_current_phase: bool = True,
) -> None:
    """将产物追加到 context.long_task_stages，并可同步更新 current_phase。"""
    raw_list = state.context.setdefault(LONG_TASK_CONTEXT_STAGES_KEY, [])
    if not isinstance(raw_list, list):
        raw_list = []
        state.context[LONG_TASK_CONTEXT_STAGES_KEY] = raw_list
    raw_list.append(artifact.model_dump(mode="json"))
    if set_current_phase:
        state.context[LONG_TASK_CONTEXT_CURRENT_PHASE_KEY] = (
            artifact.phase if isinstance(artifact.phase, str) else artifact.phase.value
        )


def parse_stage_artifacts_from_context(context: dict) -> List[StageArtifact]:
    """从黑板解析产物列表；跳过无法校验的项（健壮性）。"""
    raw = context.get(LONG_TASK_CONTEXT_STAGES_KEY)
    if not isinstance(raw, list):
        return []
    out: List[StageArtifact] = []
    for item in raw:
        if isinstance(item, dict):
            try:
                out.append(StageArtifact.model_validate(item))
            except Exception:
                continue
    return out


def get_long_task_phase_view(state: WorkflowState) -> Tuple[Optional[str], List[StageArtifact]]:
    """返回 (current_phase 字符串, 已解析产物列表)。"""
    phase = state.context.get(LONG_TASK_CONTEXT_CURRENT_PHASE_KEY)
    phase_str = str(phase) if phase is not None else None
    return phase_str, parse_stage_artifacts_from_context(state.context)


def sha256_hex_of_utf8(text: str) -> str:
    """便于在 summary 外置时填写 content_hash。"""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
