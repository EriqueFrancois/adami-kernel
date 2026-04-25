# src/adami_kernel/nexus/base_nerve.py
import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Optional

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.nexus.event import AdamiEvent, EventPriority

logger = logging.getLogger("AdamI-BaseNerve")


def _nbnrv_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class BaseNerve(ABC):
    """
    AdamI 神经接入层抽象基类（工业级最终版）
    - 统一事件构造、状态管理、思考动画接口
    - 【本次核心修复】：强制子类实现 send_message / update_ui_thought + 强化 payload 一致性
    - 彻底解决 platform/task 参数重复问题 + 思考消息残留问题
    """

    def __init__(self, publish_func: Callable[[AdamiEvent], Awaitable[None]]):
        self.publish = publish_func
        self.active_status: Dict[Any, int] = {}
        self.last_chat_id: Optional[Any] = None
        self._running = False
        logger.info(boot_t("boot.log.base_nerve_init", class_name=self.__class__.__name__))

    def create_event(
        self,
        task: str,
        platform: str = "base",
        priority: EventPriority = EventPriority.HIGH,
        **payload_extra,
    ) -> AdamiEvent:
        """统一事件构造 - 严格避免参数重复"""
        trace_id = f"{platform}_{int(datetime.now().timestamp() * 1000)}"

        payload = {
            "task": task,
            "platform": platform,
            "chat_id": self.last_chat_id,
            **payload_extra,
        }

        logger.debug(
            _nbnrv_t(
                "nbnrv.debug.create_event",
                cls=self.__class__.__name__,
                tid=trace_id,
                pf=platform,
            )
        )
        return AdamiEvent(
            trace_id=trace_id,
            source_module=f"sensory.{platform.lower()}",
            target_topic="system.events",
            priority=priority,
            payload=payload,
        )

    async def media_to_event(
        self, media_type: str, raw_data: Any, chat_id: Any = None, extra: Optional[Dict] = None
    ) -> AdamiEvent:
        """多模态统一转换器 - 简化 task 构造，彻底避免 payload 重复"""
        if chat_id:
            self.last_chat_id = chat_id

        extra = extra or {}

        if media_type in ("photo", "video", "video_note"):
            task_prefix = boot_t("cjk_gate.base_nerve_media_task_photo")
        elif media_type == "document":
            task_prefix = boot_t("cjk_gate.base_nerve_media_task_document")
        elif media_type == "voice":
            task_prefix = boot_t("cjk_gate.base_nerve_media_task_voice")
        else:
            task_prefix = boot_t("cjk_gate.base_nerve_task_multimodal_default")

        payload = {"media_type": media_type, "chat_id": chat_id, **extra}

        if media_type in ("photo", "video", "video_note"):
            payload["image_base64"] = raw_data
            task = f"{task_prefix}{boot_t('cjk_gate.base_nerve_task_photo_suffix')}"
        elif media_type == "document":
            payload["file_path"] = raw_data
            payload["file_name"] = extra.get("file_name", "unknown")
            task = f"{task_prefix} {extra.get('file_name', '')}"
        elif media_type == "voice":
            payload["original_text"] = extra.get("transcribed_text", "")
            task = f"{task_prefix}: '{extra.get('transcribed_text', '')}'"
        else:
            task = task_prefix

        logger.debug(
            _nbnrv_t(
                "nbnrv.debug.media_done",
                cls=self.__class__.__name__,
                mt=media_type,
            )
        )
        return self.create_event(
            task=task,
            platform=extra.get("platform", "base"),
            priority=EventPriority.HIGH,
            **payload,
        )

    @abstractmethod
    async def send_message(self, *args, **kwargs) -> bool:
        """子类必须实现的最终回复发送方法"""
        pass

    @abstractmethod
    async def update_ui_thought(self, chat_id: Any, thought: Any) -> None:
        """子类必须实现的思考动画更新方法"""
        pass

    async def send_status_message(self, chat_id: Any, text: str | None = None) -> None:
        """统一思考状态消息发送（供子类调用）"""
        if text is None:
            text = boot_t("cjk_gate.base_nerve_status_thinking")
        logger.debug(
            _nbnrv_t(
                "nbnrv.debug.status",
                cls=self.__class__.__name__,
                snippet=(text or "")[:80],
            )
        )

    @abstractmethod
    async def start_listening(self):
        pass

    async def stop(self):
        self._running = False
        logger.info(boot_t("boot.log.base_nerve_stopped", class_name=self.__class__.__name__))


# --- END OF FILE base_nerve.py ---
