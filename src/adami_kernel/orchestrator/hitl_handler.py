# --- START OF FILE hitl_handler.py ---
from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Dict, Optional

from pydantic import BaseModel

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.nexus.bus import EventBus

if TYPE_CHECKING:
    from adami_kernel.nexus.telegram_sensory import TelegramSensory
    from adami_kernel.orchestrator.workflow_engine import WorkflowEngine

logger = logging.getLogger("AdamI-HITLHandler")


def _hitl_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class HitlEvent(BaseModel):
    """HITL 专用事件结构"""

    event_type: str  # "PAUSED" 或 "RESUME"
    workflow_id: str
    chat_id: str
    reason: str = ""
    user_input: Optional[Dict[str, Any]] = None
    timestamp: Optional[str] = None


class HitlHandler:
    """
    AdamI 2.0 强力 Human-in-the-Loop（HITL）处理器
    统一管理 PAUSED / RESUME 事件、Telegram 交互按钮推送、用户输入注入。
    触发条件：高危动作、连续失败3次、需要外部授权。
    【本次核心修复】：新增事件监听循环，彻底实现 EventBus 解耦
    """

    def __init__(
        self,
        bus: EventBus,
        telegram_nerve: Optional[TelegramSensory] = None,
        workflow_engine: Optional["WorkflowEngine"] = None,
    ):
        self.bus = bus
        self.telegram_nerve = telegram_nerve  # 运行时注入
        self.workflow_engine = workflow_engine
        self.active_paused_workflows: Dict[str, HitlEvent] = {}
        self._subscription_task: Optional[asyncio.Task] = None
        # Step 8.1: ACTION-family intent templates — Telegram one-shot ack (no template side effects until consumed).
        self._intent_action_template_ack_chats: set[str] = set()
        logger.info(_hitl_t("hitl.log.init"))

    def set_telegram_nerve(self, nerve):
        """运行时注入 TelegramNerve（彻底解决循环导入）"""
        self.telegram_nerve = nerve
        logger.info(_hitl_t("hitl.log.tg_injected"))

    def grant_intent_action_template_ack(self, chat_id: str) -> None:
        """Telegram (or other UI) approved running ACTION preset templates for this chat once."""
        self._intent_action_template_ack_chats.add(str(chat_id).strip())

    def consume_intent_action_template_ack(self, chat_id: str) -> bool:
        """If a one-shot ack is pending for ``chat_id``, remove it and return ``True``."""
        cid = str(chat_id).strip()
        if cid in self._intent_action_template_ack_chats:
            self._intent_action_template_ack_chats.discard(cid)
            return True
        return False

    async def prompt_intent_action_template_confirmation(
        self, chat_id: str, task_excerpt: str
    ) -> None:
        """
        Step 8.1: push Telegram inline buttons so the user can confirm before ACTION templates run.
        Falls back to caller when ``telegram_nerve`` is missing.
        """
        if not self.telegram_nerve:
            return
        loc = settings.effective_ui_default_locale()
        excerpt = (task_excerpt or "").strip()
        if len(excerpt) > 400:
            excerpt = excerpt[:397] + "…"
        body = t(
            "intent.action_template.hitl_body",
            excerpt=excerpt or "—",
            locale=loc,
        )
        cid = str(chat_id).strip()
        buttons = [
            {
                "text": t("intent.action_template.hitl_btn_confirm", locale=loc),
                "callback_data": f"intent_action_tpl:approve:{cid}",
            },
            {
                "text": t("intent.action_template.hitl_btn_abort", locale=loc),
                "callback_data": f"intent_action_tpl:cancel:{cid}",
            },
        ]
        try:
            await self.telegram_nerve.send_interactive_buttons(
                int(cid) if cid.isdigit() else int(float(cid)),
                body,
                buttons,
            )
        except (TypeError, ValueError):
            logger.warning("[HITLHandler] intent ACTION confirm: invalid chat_id=%r", cid)

    async def initialize(self):
        """启动 HITL 监听器（``ADAMI_ENABLE_HITL`` 关闭时跳过 ``hitl.events`` 订阅，仅保留实例能力）。"""
        if bool(getattr(settings, "ADAMI_ENABLE_HITL", False)):
            self._subscription_task = asyncio.create_task(self._listen_hitl_events())
            logger.info(_hitl_t("hitl.log.subscribed"))
        else:
            logger.debug("[HITLHandler] ADAMI_ENABLE_HITL=false; skip hitl.events listener")

    async def _listen_hitl_events(self):
        """监听 HITL 专用事件"""
        q = await self.bus.subscribe("hitl.events")
        while True:
            try:
                event = await asyncio.wait_for(
                    q.get(), timeout=float(settings.ADAMI_ORCHESTRATOR_QUEUE_POLL_SEC)
                )
                if event.target_topic == "hitl.events":
                    payload = event.payload
                    workflow_id = payload.get("workflow_id")
                    chat_id = payload.get("chat_id")
                    reason = payload.get("reason")

                    # 在收到事件时，才调用 trigger_paused 推送 Telegram 按钮
                    await self.trigger_paused(workflow_id, chat_id, reason)
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(_hitl_t("hitl.err.listen", e=e))

    async def trigger_paused(self, workflow_id: str, chat_id: str, reason: str) -> None:
        """触发 PAUSED 状态并推送交互按钮"""
        event = HitlEvent(
            event_type="PAUSED", workflow_id=workflow_id, chat_id=chat_id, reason=reason
        )
        self.active_paused_workflows[workflow_id] = event

        if self.telegram_nerve:
            loc = settings.effective_ui_default_locale()
            buttons = [
                {
                    "text": t("orch.hitl.btn_retry", locale=loc),
                    "callback_data": f"resume:{workflow_id}:retry",
                },
                {
                    "text": t("orch.hitl.btn_provide_extra", locale=loc),
                    "callback_data": f"resume:{workflow_id}:provide",
                },
                {
                    "text": t("orch.hitl.btn_cancel_task", locale=loc),
                    "callback_data": f"resume:{workflow_id}:cancel",
                },
            ]
            await self.telegram_nerve.send_interactive_buttons(
                chat_id=int(chat_id),
                text=t("orch.hitl.paused_message", reason=reason, locale=loc),
                buttons=buttons,
            )
            logger.info(_hitl_t("hitl.log.paused_buttons", wid=workflow_id))
        else:
            logger.warning(_hitl_t("hitl.warn.paused_no_tg", wid=workflow_id))

        await self.bus.publish(
            {
                "type": "HITL_PAUSED",
                "workflow_id": workflow_id,
                "chat_id": chat_id,
                "reason": reason,
            }
        )

    async def process_resume(
        self, workflow_id: str, action: str, user_input: Optional[Dict[str, Any]] = None
    ) -> None:
        """处理 RESUME 事件。步骤 4.1：action=replay 时 user_input 需含 replay_phase，走 resume_mode=replay_from_phase。"""
        if workflow_id not in self.active_paused_workflows:
            logger.warning(_hitl_t("hitl.warn.resume_missing", wid=workflow_id))
            return

        self.active_paused_workflows.pop(workflow_id)

        if action == "retry":
            await self.workflow_engine.resume_workflow(
                workflow_id, user_input={"resume_mode": "continue", "action": "retry"}
            )
        elif action == "provide" and user_input:
            ui = dict(user_input)
            ui.setdefault("resume_mode", "continue")
            await self.workflow_engine.resume_workflow(workflow_id, user_input=ui)
        elif action == "replay":
            rp = (user_input or {}).get("replay_phase", "research")
            await self.workflow_engine.resume_workflow(
                workflow_id,
                user_input={
                    "resume_mode": "replay_from_phase",
                    "replay_phase": str(rp),
                    "action": "replay",
                },
            )
        elif action == "cancel":
            await self.workflow_engine.cancel_workflow(workflow_id)

        logger.info(_hitl_t("hitl.log.resumed", wid=workflow_id, action=action))

        await self.bus.publish(
            {
                "type": "HITL_RESUME",
                "workflow_id": workflow_id,
                "action": action,
                "user_input": user_input,
            }
        )


# ====================== 全局单例 ======================
hitl_handler = None  # kernel boot 时由 kernel 完成注入
# =================================================================================

# --- END OF FILE hitl_handler.py ---
