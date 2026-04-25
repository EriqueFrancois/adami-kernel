import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field

from adami_kernel.config import settings
from adami_kernel.i18n import t


def _wf_desc(key: str) -> str:
    return t(key, locale=settings.effective_ui_default_locale())


class Node(BaseModel):
    """
    工作流节点定义 - 工业级强类型节点
    每个节点代表一个原子执行单元（LLM调用、工具执行、条件判断等）
    """

    node_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()), description=_wf_desc("wf.field.node_id")
    )
    # 扩展节点类型，支持 SkillComposer 生成的 SKILL_CALL 和 LLM_CALL
    node_type: Literal[
        "LLM",
        "TOOL",
        "CONDITION",
        "HUMAN",
        "START",
        "END",
        "SKILL_CALL",
        "LLM_CALL",
        "DELEGATE_DEERFLOW",
    ] = Field(..., description=_wf_desc("wf.field.node_type"))
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description=_wf_desc("wf.field.node_config"),
    )
    timeout: int = Field(default=60, description=_wf_desc("wf.field.node_timeout"))
    max_retries: int = Field(default=3, description=_wf_desc("wf.field.node_max_retries"))
    description: Optional[str] = Field(
        default=None, description=_wf_desc("wf.field.node_description")
    )


class WorkflowState(BaseModel):
    """
    工作流完整状态模型 - 持久化核心
    所有工作流实例均以此结构存储到 LayeredMemory 的 workflow_state 域
    """

    workflow_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()), description=_wf_desc("wf.field.workflow_id")
    )
    chat_id: str = Field(..., description=_wf_desc("wf.field.chat_id"))

    status: Literal["PENDING", "RUNNING", "PAUSED", "SUCCESS", "FAILED", "CANCELLED"] = Field(
        default="PENDING", description=_wf_desc("wf.field.status")
    )

    current_node_id: Optional[str] = Field(
        default=None, description=_wf_desc("wf.field.current_node_id")
    )
    nodes: Dict[str, Node] = Field(default_factory=dict, description=_wf_desc("wf.field.nodes"))
    edges: Dict[str, List[str]] = Field(
        default_factory=dict, description=_wf_desc("wf.field.edges")
    )

    context: Dict[str, Any] = Field(
        default_factory=dict,
        description=_wf_desc("wf.field.context"),
    )
    history: List[Dict[str, Any]] = Field(
        default_factory=list,
        description=_wf_desc("wf.field.history"),
    )

    error_retry_counts: Dict[str, int] = Field(
        default_factory=dict, description=_wf_desc("wf.field.error_retry_counts")
    )
    global_step_count: int = Field(default=0, description=_wf_desc("wf.field.global_step_count"))
    max_steps: int = Field(default=50, description=_wf_desc("wf.field.max_steps"))

    version: int = Field(default=1, description=_wf_desc("wf.field.version"))
    parent_workflow_id: Optional[str] = Field(
        default=None, description=_wf_desc("wf.field.parent_workflow_id")
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict,
        description=_wf_desc("wf.field.metadata"),
    )

    created_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description=_wf_desc("wf.field.created_at"),
    )
    last_updated: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description=_wf_desc("wf.field.last_updated"),
    )

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat()}


class WorkflowEvent(BaseModel):
    """
    工作流事件载体 - 用于 EventBus 传递
    所有节点执行结果、状态变更均通过此事件在总线中流转
    """

    trace_id: str = Field(
        default_factory=lambda: f"wf_{int(datetime.now(timezone.utc).timestamp()*1000)}"
    )
    workflow_id: str
    node_id: Optional[str] = None
    event_type: Literal[
        "NODE_START",
        "NODE_COMPLETE",
        "NODE_FAILED",
        "WORKFLOW_PAUSED",
        "WORKFLOW_RESUMED",
        "WORKFLOW_SUCCESS",
        "WORKFLOW_FAILED",
        "PHASE_TRANSITION",
    ]
    payload: Dict[str, Any] = Field(default_factory=dict)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


# ====================== 辅助工具函数 ======================
def ensure_default_profile_id(state: WorkflowState, profile_id: str) -> None:
    """Set ``metadata['profile_id']`` if absent.

    Orchestration-only tag for logs and filtering; not used by Report Studio or SecondBrain paths.
    """
    state.metadata.setdefault("profile_id", profile_id)


def generate_workflow_id() -> str:
    """生成工作流ID（供外部调用）"""
    return f"wf_{uuid.uuid4().hex[:12]}"


def create_initial_workflow_state(chat_id: str, task_description: str = "") -> WorkflowState:
    """快速创建初始工作流状态（供 Planner 调用）"""
    state = WorkflowState(
        chat_id=chat_id,
        status="PENDING",
        context={"original_task": task_description},
        nodes={
            "__start__": Node(
                node_id="__start__",
                node_type="START",
                description=_wf_desc("wf.create.start_description"),
            )
        },
        edges={"__start__": []},
    )
    ensure_default_profile_id(state, "planner_initial")
    return state
