# src/adami_kernel/guardian/rbac_initializer.py
# --- START OF FILE rbac_initializer.py ---

import logging

from adami_kernel.guardian.rbac import RBACMatrix

logger = logging.getLogger("AdamI-RBACInitializer")


class RBACInitializer:
    """
    AdamI RBAC 初始化器（工业级权限矩阵）
    【本次核心修复】：为 sensory.telegram 和 sensory.discord 授予 system.events 发布权限
    """

    @staticmethod
    def initialize(rbac: RBACMatrix):
        """同步初始化所有模块的 RBAC 权限（兼容 kernel.py 同步调用）"""
        # ====================== 【核心权限矩阵】 ======================
        # multi_agent_orchestrator 多代理编排器权限（必须允许发布任务）
        rbac.grant("multi_agent_orchestrator", "agent.communication")
        rbac.grant("multi_agent_orchestrator", "workflow.events")
        rbac.grant("multi_agent_orchestrator", "hitl.events")
        rbac.grant("multi_agent_orchestrator", "system.events")

        # planner 权限
        rbac.grant("planner", "workflow.events")
        rbac.grant("planner", "agent.communication")
        rbac.grant("planner", "system.events")

        # workflow_engine 权限
        rbac.grant("workflow_engine", "workflow.events")
        rbac.grant("workflow_engine", "hitl.events")

        # decision_processor 权限
        rbac.grant("decision_processor", "system.events")
        rbac.grant("decision_processor", "workflow.events")

        # sensitive_filter 权限
        rbac.grant("sensitive_filter", "system.events")

        # ====================== 【本次核心修复】Nerve/Sensory 权限 ======================
        # Telegram Sensory（模块名来自 telegram_sensory.py 中的 source_module）
        rbac.grant("sensory.telegram", "system.events")
        rbac.grant("sensory.telegram", "agent.communication")

        # Discord Nerve
        rbac.grant("sensory.discord", "system.events")
        rbac.grant("sensory.discord", "agent.communication")
        rbac.grant("discord_nerve", "system.events")
        rbac.grant("discord_nerve", "agent.communication")

        # 通用 sensory 模块（保底）
        rbac.grant("sensory", "system.events")
        # =================================================================================

        logger.info("[RBACInitializer] permissions initialized")
        # =================================================================================


# --- END OF FILE rbac_initializer.py ---
