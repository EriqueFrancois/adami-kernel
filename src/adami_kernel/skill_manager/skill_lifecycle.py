# --- START OF FILE skill_lifecycle.py ---
"""
AdamI Skill Manager - SkillLifecycle（统一生命周期管理）

定义技能全生命周期状态机（CREATED → VALIDATED → LOADED → ACTIVE → DEPRECATED）。
支持状态流转、事件发布和审计追溯，符合单一职责原则。
"""

import logging
from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable, Optional

from adami_kernel.i18n.boot_msg import boot_t

logger = logging.getLogger("AdamI-SkillLifecycle")


class SkillStatus(Enum):
    """技能生命周期状态枚举"""

    CREATED = auto()  # 已生成原始代码
    VALIDATED = auto()  # 通过语法/安全/签名验证
    LOADED = auto()  # 已动态加载到内存
    ACTIVE = auto()  # 已注册并可执行
    DEPRECATED = auto()  # 连续失败或分数过低（待清理）


@dataclass
class SkillLifecycle:
    """
    技能生命周期管理器（单一职责）
    每个技能对应一个实例，由 SkillManager 统一持有。
    """

    skill_name: str
    current_status: SkillStatus = SkillStatus.CREATED
    created_at: float = 0.0
    last_transition_at: float = 0.0
    transition_history: list = None
    on_status_changed: Optional[Callable[[str, SkillStatus, SkillStatus], None]] = (
        None  # 事件回调（可选）
    )

    def __post_init__(self):
        if self.transition_history is None:
            self.transition_history = []
        import time

        self.created_at = time.time()
        self.last_transition_at = self.created_at
        self.transition_history.append(
            (self.current_status, boot_t("cjk_gate.skill_lifecycle_initial_reason"))
        )

    def transition_to(self, new_status: SkillStatus, reason: str = "") -> bool:
        """
        状态流转（仅允许合法转换）
        """
        # 相同状态直接返回成功，不记录警告
        if new_status == self.current_status:
            logger.debug(
                boot_t(
                    "boot.log.skill_lifecycle_unchanged",
                    skill=self.skill_name,
                    status=self.current_status.name,
                    reason=reason,
                )
            )
            return True

        valid_transitions = {
            SkillStatus.CREATED: {SkillStatus.VALIDATED},
            SkillStatus.VALIDATED: {SkillStatus.LOADED},
            SkillStatus.LOADED: {SkillStatus.ACTIVE},
            SkillStatus.ACTIVE: {SkillStatus.DEPRECATED},
            SkillStatus.DEPRECATED: set(),  # 终态
        }

        if new_status not in valid_transitions.get(self.current_status, set()):
            # 降低日志级别为 debug（不影响业务）
            logger.debug(
                boot_t(
                    "boot.log.skill_lifecycle_invalid_transition",
                    skill=self.skill_name,
                    old_status=self.current_status.name,
                    new_status=new_status.name,
                )
            )
            return False

        old_status = self.current_status
        self.current_status = new_status
        import time

        self.last_transition_at = time.time()
        self.transition_history.append((new_status, reason))

        logger.info(
            boot_t(
                "boot.log.skill_lifecycle_transition",
                skill=self.skill_name,
                old_status=old_status.name,
                new_status=new_status.name,
                reason=reason,
            )
        )

        # 事件发布（可选）
        if self.on_status_changed:
            self.on_status_changed(self.skill_name, old_status, new_status)

        return True

    def get_status(self) -> SkillStatus:
        """获取当前状态"""
        return self.current_status

    def get_history(self) -> list:
        """返回完整状态流转历史"""
        return self.transition_history

    def is_active(self) -> bool:
        """快捷判断是否处于可执行状态"""
        return self.current_status == SkillStatus.ACTIVE


# --- END OF FILE skill_lifecycle.py ---
