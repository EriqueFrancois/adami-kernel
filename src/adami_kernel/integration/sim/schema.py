"""可回放轨迹 NDJSON 契约（v1）。与 Sim 解耦，供步骤 2 Replayer 与可选 Webhook 消费。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from adami_kernel.config import settings
from adami_kernel.i18n import t as i18n_t

TRACE_SCHEMA_V1 = "adami_replay_trace.v1"


def _sim_t(key: str, **kwargs: object) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class ReplayTraceRecordV1(BaseModel):
    """单条 EventBus 观测记录（脱敏后）。

    模块四：``phase`` / ``checkpoint_seq`` 在 ``PHASE_TRANSITION`` 等长任务事件上填充，
    便于 Sim NDJSON 回放统计阶段边界与 checkpoint 序号（与 ``WorkflowState.history`` 对齐）。
    """

    schema_version: str = Field(default=TRACE_SCHEMA_V1)
    ts: float
    trace_id: str
    episode_id: Optional[str] = None
    source_module: str
    target_topic: str
    event_type: str = "adami_event"
    payload_redacted: Dict[str, Any] = Field(default_factory=dict)
    phase: Optional[str] = Field(
        default=None,
        description=_sim_t("sim.field.phase"),
    )
    checkpoint_seq: Optional[int] = Field(
        default=None,
        description=_sim_t("sim.field.checkpoint_seq"),
    )

    def to_ndjson_line(self) -> str:
        return self.model_dump_json() + "\n"
