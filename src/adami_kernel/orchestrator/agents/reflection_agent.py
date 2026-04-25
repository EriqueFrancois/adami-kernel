# --- START OF FILE reflection_agent.py ---

import logging

from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.orchestrator.agent_models import AgentMessage, AgentRole
from adami_kernel.orchestrator.reflexion_loop import ReflexionLoop

logger = logging.getLogger("AdamI-ReflectionAgent")


class ReflectionAgent:
    """
    AdamI 2.0 ReflectionAgent（反思代理）
    职责：作为独立代理处理 ReflexionLoop 的具体执行
    与其他 4 类代理（Researcher/Engineer/Critic/Human）保持统一接口
    """

    def __init__(self, memory: LayeredMemory, reflexion_loop: ReflexionLoop):
        self.memory = memory
        self.reflexion_loop = reflexion_loop
        logger.info(boot_t("boot.log.reflection_agent_init"))

    async def process(self, msg: AgentMessage) -> AgentMessage:
        """处理 Orchestrator 或 Critic 下发的反思任务"""
        if msg.message_type != "task":
            return AgentMessage(
                source_agent=AgentRole.CRITIC,
                target_agent=AgentRole.ORCHESTRATOR,
                message_type="error",
                payload={"error": boot_t("cjk_gate.agent_error_non_task")},
                chat_id=msg.chat_id,
            )

        failure_context = msg.payload.get("failure_context", {})
        workflow_id = msg.workflow_id
        chat_id = msg.chat_id

        logger.info(boot_t("boot.log.reflection_task_triggered", workflow_id=workflow_id))

        try:
            # 调用 ReflexionLoop 执行完整自愈流程
            success = await self.reflexion_loop.trigger_reflexion(
                workflow_id=workflow_id, chat_id=chat_id, failure_context=failure_context
            )

            return AgentMessage(
                source_agent=AgentRole.CRITIC,
                target_agent=AgentRole.ORCHESTRATOR,
                message_type="result" if success else "error",
                payload={
                    "reflexion_success": success,
                    "message": (
                        boot_t("cjk_gate.reflection_message_ok")
                        if success
                        else boot_t("cjk_gate.reflection_message_fail")
                    ),
                },
                workflow_id=workflow_id,
                chat_id=chat_id,
            )

        except Exception as e:
            logger.error(boot_t("boot.log.reflection_exec_failed", detail=str(e)), exc_info=True)
            return AgentMessage(
                source_agent=AgentRole.CRITIC,
                target_agent=AgentRole.ORCHESTRATOR,
                message_type="error",
                payload={"error": str(e)},
                chat_id=chat_id,
            )


# --- END OF FILE reflection_agent.py ---
