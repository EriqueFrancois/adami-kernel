from enum import Enum
from typing import Any, Dict

from pydantic import BaseModel


class EventPriority(Enum):
    """
    事件优先级枚举
    URGENT: 用于外部感官刺激，具有最高中断优先级
    HIGH: 用于用户直接指令或关键反馈
    NORMAL: 常规系统心跳与后台任务
    LOW: 异步日志或非关键自检
    """

    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4  # 补全 URGENT 优先级，防止 Sensory 模块报错


class AdamiEvent(BaseModel):
    """
    AdamI 核心事件数据结构
    """

    trace_id: str
    source_module: str
    target_topic: str
    priority: EventPriority
    payload: Dict[str, Any]
