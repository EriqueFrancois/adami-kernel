# --- START OF FILE agent_models.py ---

import logging
import uuid
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

# 复用阶段1 WorkflowState（确保工作流状态无缝对接）
from adami_kernel.config import settings
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.boot_msg import boot_t


def _agmd_d(key: str) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale())


logger = logging.getLogger("AdamI-AgentModels")


class AgentRole(StrEnum):
    """代理角色枚举（工业级 StrEnum，Pydantic v2 原生支持）"""

    ORCHESTRATOR = "Orchestrator"
    RESEARCHER = "Researcher"
    ENGINEER = "Engineer"
    CRITIC = "Critic"
    HUMAN = "Human"
    EXECUTOR = "Executor"  # 新增：执行代理，负责调用技能并返回结果


class AgentMessage(BaseModel):
    """
    多代理通信标准消息结构（阶段2 核心协议）
    所有代理间通信必须使用此模型，确保可追溯、可审计、可持久化
    """

    trace_id: str = Field(
        default_factory=lambda: f"agent_{uuid.uuid4().hex[:12]}",
        description=_agmd_d("agmd.field.trace_id"),
    )
    source_agent: AgentRole = Field(..., description=_agmd_d("agmd.field.source_agent"))
    target_agent: AgentRole = Field(..., description=_agmd_d("agmd.field.target_agent"))
    message_type: Literal["task", "result", "feedback", "pause", "resume", "error"] = Field(
        ...,
        description=_agmd_d("agmd.field.message_type"),
    )
    payload: Dict[str, Any] = Field(
        default_factory=dict,
        description=_agmd_d("agmd.field.payload"),
    )
    workflow_id: Optional[str] = Field(None, description=_agmd_d("agmd.field.workflow_id"))
    chat_id: str = Field(..., description=_agmd_d("agmd.field.chat_id"))
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description=_agmd_d("agmd.field.timestamp"),
    )
    version: int = Field(default=1, description=_agmd_d("agmd.field.version"))

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}
        use_enum_values = True  # StrEnum 序列化时输出字符串

    def to_event_payload(self) -> Dict[str, Any]:
        """转换为 EventBus 可发布的 payload"""
        return self.model_dump(mode="json")


class AgentTask(BaseModel):
    """单个代理任务定义（Orchestrator 生成后分发）"""

    task_id: str = Field(default_factory=lambda: f"task_{uuid.uuid4().hex[:8]}")
    agent_role: AgentRole
    description: str
    required_output_schema: Dict[str, Any]  # JSON Schema，用于 Critic 校验
    context_keys: List[str] = Field(default_factory=list)  # 需要从 WorkflowState.context 读取的键
    timeout_seconds: int = Field(default=120)


class AgentFeedback(BaseModel):
    """Critic 审计反馈结构（强制契约化输出）"""

    approved: bool
    feedback: str
    suggestions: List[str] = Field(default_factory=list)
    retry_count: int = Field(default=0)


logger.info(boot_t("boot.log.agent_models_loaded"))

# --- END OF FILE agent_models.py ---
