# --- START OF FILE executor.py ---

import logging
from typing import Any, Optional

from adami_kernel.config import settings
from adami_kernel.cortex.evolution import EvolutionEngine
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.i18n import t as i18n_t
from adami_kernel.orchestrator.agent_models import AgentMessage, AgentRole
from adami_kernel.skill_manager.skill_router import SkillRouter
from adami_kernel.skill_manager.skill_version_manager import SkillVersionManager

logger = logging.getLogger("AdamI-Executor")


def _exec_t(key: str, **kwargs: Any) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class ExecutorAgent:
    """
    执行代理（Phase 3 增强版 + 直接调用支持）
    职责：通过 SkillRouter 获取技能调用规范，执行技能，并记录执行结果到 SkillVersionManager。
    增强：支持从 Orchestrator 直接传入 skill_name 和 args，避免重复路由。
    【BugFix 第十五步】强化异常容错（unhashable type: 'dict' 等坏技能），防止异常泄漏到 orchestrator。
    """

    def __init__(
        self,
        evolution_engine: EvolutionEngine,
        memory: LayeredMemory,
        skill_router: Optional[SkillRouter] = None,
        skill_version_manager: Optional[SkillVersionManager] = None,
    ):
        self.evolution_engine = evolution_engine
        self.memory = memory
        self.skill_router = skill_router
        self.skill_version_manager = skill_version_manager
        logger.debug("[Executor] ready")

    def _extract_skill_name(self, obj: Any) -> Optional[str]:
        """从可能的对象中提取技能名称（兼容多种结构）"""
        if isinstance(obj, str):
            return obj
        if isinstance(obj, dict):
            for key in ["skill_name", "name", "skill"]:
                if key in obj and obj[key]:
                    return str(obj[key])
            for v in obj.values():
                if isinstance(v, str) and v:
                    return v
        return None

    async def process(self, msg: AgentMessage) -> AgentMessage:
        """处理执行任务"""
        if msg.message_type != "task":
            return AgentMessage(
                source_agent=AgentRole.EXECUTOR,
                target_agent=AgentRole.ORCHESTRATOR,
                message_type="error",
                payload={"error": _exec_t("exec.err.not_task")},
                workflow_id=msg.workflow_id,
                chat_id=msg.chat_id,
            )

        # ====================== 优先使用直接传递的技能名和参数 ======================
        skill_name = msg.payload.get("skill_name")
        args = msg.payload.get("args", {})

        if skill_name:
            logger.info(_exec_t("exec.log.direct_call", skill_name=skill_name, args=args))
        else:
            # ====================== 路由阶段（原有逻辑） ======================
            context = msg.payload.get("context", {})
            original_user_task = context.get("original_user_task", "") or msg.payload.get(
                "original_task", ""
            )
            if not original_user_task:
                logger.warning(_exec_t("exec.log.no_user_task"))
                return AgentMessage(
                    source_agent=AgentRole.EXECUTOR,
                    target_agent=AgentRole.ORCHESTRATOR,
                    message_type="error",
                    payload={"error": _exec_t("exec.err.no_user_task")},
                    workflow_id=msg.workflow_id,
                    chat_id=msg.chat_id,
                )

            logger.info(_exec_t("exec.log.user_task", snippet=original_user_task[:100]))

            if self.skill_router is not None:
                spec = await self.skill_router.get_call_spec(original_user_task)
                if spec is not None:
                    skill_name, args = spec
                    logger.info(_exec_t("exec.log.router_match", skill_name=skill_name, args=args))
                else:
                    logger.warning(_exec_t("exec.log.router_none"))
                    return AgentMessage(
                        source_agent=AgentRole.EXECUTOR,
                        target_agent=AgentRole.ORCHESTRATOR,
                        message_type="error",
                        payload={"error": _exec_t("exec.err.no_skill")},
                        workflow_id=msg.workflow_id,
                        chat_id=msg.chat_id,
                    )
            else:
                previous_result = msg.payload.get("result", {})
                skill_name = self._extract_skill_name(previous_result) or self._extract_skill_name(
                    msg.payload
                )
                if not skill_name:
                    logger.warning(_exec_t("exec.log.no_router_name"))
                    return AgentMessage(
                        source_agent=AgentRole.EXECUTOR,
                        target_agent=AgentRole.ORCHESTRATOR,
                        message_type="error",
                        payload={"error": _exec_t("exec.err.no_skill_name")},
                        workflow_id=msg.workflow_id,
                        chat_id=msg.chat_id,
                    )
                args = msg.payload.get("args", {})
                logger.info(_exec_t("exec.log.fallback_call", skill_name=skill_name, args=args))

        # ====================== 执行技能（强化异常捕获） ======================
        skill_func = self.evolution_engine.get_skill(skill_name)
        if not skill_func:
            logger.warning(_exec_t("exec.log.skill_not_loaded", skill_name=skill_name))
            if self.skill_version_manager:
                await self.skill_version_manager.record_execution_result(
                    skill_name,
                    success=False,
                    details={"error": _exec_t("exec.detail.not_loaded")},
                )
            return AgentMessage(
                source_agent=AgentRole.EXECUTOR,
                target_agent=AgentRole.ORCHESTRATOR,
                message_type="error",
                payload={"error": _exec_t("exec.err.skill_missing", skill_name=skill_name)},
                workflow_id=msg.workflow_id,
                chat_id=msg.chat_id,
            )

        try:
            # 安全拷贝 args，防止 dict unhashable
            safe_args = {k: (v.copy() if isinstance(v, dict) else v) for k, v in args.items()}
            logger.info(_exec_t("exec.log.invoke", skill_name=skill_name, safe_args=safe_args))
            result = await skill_func(**safe_args)
            logger.info(_exec_t("exec.log.done", skill_name=skill_name, result=result))
        except Exception as e:
            error_msg = str(e)
            logger.error(
                _exec_t("exec.log.invoke_fail", skill_name=skill_name, error_msg=error_msg)
            )
            if self.skill_version_manager:
                await self.skill_version_manager.record_execution_result(
                    skill_name, success=False, details={"error": error_msg}
                )
            return AgentMessage(
                source_agent=AgentRole.EXECUTOR,
                target_agent=AgentRole.ORCHESTRATOR,
                message_type="error",
                payload={"error": error_msg},
                workflow_id=msg.workflow_id,
                chat_id=msg.chat_id,
            )

        # 判断技能执行是否成功（基于返回结果中的 status）
        success = False
        if isinstance(result, dict):
            if result.get("status") == "success":
                success = True
            elif result.get("status") == "error":
                success = False
            else:
                success = True
        else:
            success = True

        # 记录执行结果到 SkillVersionManager
        if self.skill_version_manager:
            details = {"result": result} if isinstance(result, dict) else {"result": str(result)}
            await self.skill_version_manager.record_execution_result(
                skill_name, success=success, details=details
            )

        # 返回标准结构（避免 unhashable 问题）
        return AgentMessage(
            source_agent=AgentRole.EXECUTOR,
            target_agent=AgentRole.ORCHESTRATOR,
            message_type="result",
            payload={"result": {"execution_result": result}},
            workflow_id=msg.workflow_id,
            chat_id=msg.chat_id,
        )


# --- END OF FILE executor.py ---
