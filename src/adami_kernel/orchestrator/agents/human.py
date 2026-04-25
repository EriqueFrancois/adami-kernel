# --- START OF FILE human.py ---

import logging
from typing import Any, Optional, Protocol, runtime_checkable

from adami_kernel.config import settings
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.orchestrator.agent_models import AgentMessage, AgentRole

logger = logging.getLogger("AdamI-Human")


@runtime_checkable
class _TelegramButtons(Protocol):
    async def send_interactive_buttons(
        self, chat_id: int, text: str, buttons: list[dict]
    ) -> Any: ...


@runtime_checkable
class _DiscordButtons(Protocol):
    async def send_interactive_buttons(
        self, channel_id: str, text: str, buttons: list[dict]
    ) -> Any: ...


class Human:
    """
    AdamI 2.0 Human 代理（人类兜底代理）
    职责：当连续失败或需要强授权操作时，通过 Telegram/Discord 向用户发送交互按钮
    支持暂停工作流、用户回复后自动 RESUME
    """

    def __init__(
        self,
        memory: LayeredMemory,
        telegram_nerve: Optional[Any] = None,
        discord_nerve: Optional[Any] = None,
    ):
        self.memory = memory
        self.telegram_nerve = telegram_nerve
        self.discord_nerve = discord_nerve
        logger.info(boot_t("boot.log.human_agent_init"))

    async def process(self, msg: AgentMessage) -> AgentMessage:
        """处理 Orchestrator 下发的人类介入任务"""
        if msg.message_type != "task":
            return AgentMessage(
                source_agent=AgentRole.HUMAN,
                target_agent=AgentRole.ORCHESTRATOR,
                message_type="error",
                payload={"error": boot_t("cjk_gate.agent_error_non_task")},
                chat_id=msg.chat_id,
            )

        task = msg.payload.get("task", {})
        loc = settings.effective_ui_default_locale()
        reason = task.get("reason") or t("orch.human.default_reason", locale=loc)
        workflow_id = msg.workflow_id

        logger.info(
            boot_t(
                "boot.log.human_intervention_triggered",
                workflow_id=workflow_id,
                reason=reason,
            )
        )

        try:
            human_message = t(
                "orch.human.intervention_message",
                workflow_id=workflow_id,
                reason=reason,
                locale=loc,
            )

            buttons = [
                {
                    "text": t("orch.human.btn_continue", locale=loc),
                    "callback_data": f"resume:{workflow_id}:continue",
                },
                {
                    "text": t("orch.human.btn_pause", locale=loc),
                    "callback_data": f"resume:{workflow_id}:pause",
                },
                {
                    "text": t("orch.human.btn_provide", locale=loc),
                    "callback_data": f"resume:{workflow_id}:provide",
                },
            ]
            if self.telegram_nerve and isinstance(self.telegram_nerve, _TelegramButtons):
                await self.telegram_nerve.send_interactive_buttons(
                    chat_id=int(msg.chat_id), text=human_message, buttons=buttons
                )
            elif self.discord_nerve and isinstance(self.discord_nerve, _DiscordButtons):
                await self.discord_nerve.send_interactive_buttons(
                    channel_id=str(msg.chat_id), text=human_message, buttons=buttons
                )

            # 3. 暂存等待状态（Human 回复后由 Nerve 触发 RESUME 事件）
            await self.memory.store_experience(
                trace_id=msg.trace_id,
                domain=f"human_waiting_{msg.chat_id}",
                payload={"workflow_id": workflow_id, "status": "waiting"},
                chat_id=msg.chat_id,
            )

            # 4. 返回等待消息给 Orchestrator
            return AgentMessage(
                source_agent=AgentRole.HUMAN,
                target_agent=AgentRole.ORCHESTRATOR,
                message_type="pause",
                payload={"status": "waiting_for_human", "reason": reason},
                workflow_id=workflow_id,
                chat_id=msg.chat_id,
            )

        except Exception as e:
            logger.error(boot_t("boot.log.human_intervention_failed", detail=str(e)), exc_info=True)
            return AgentMessage(
                source_agent=AgentRole.HUMAN,
                target_agent=AgentRole.ORCHESTRATOR,
                message_type="error",
                payload={"error": str(e)},
                chat_id=msg.chat_id,
            )


# --- END OF FILE human.py ---
