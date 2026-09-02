# --- START OF FILE bus.py ---

import asyncio
import json
import logging
from collections import defaultdict
from typing import Any, Awaitable, Callable

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.integration.sim.trace_sink import (
    get_trace_sink,
    offer_trace_event_for_system_path,
)
from adami_kernel.nexus.event import AdamiEvent, EventPriority

logger = logging.getLogger("AdamI-EventBus")


def _nbus_msg(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class EventBus:
    def __init__(self):
        self.subscribers = defaultdict(list)
        self.middlewares = []
        self.dlq_db = None
        self._replay_task = None
        self.rbac = None

    def set_rbac(self, rbac) -> None:
        self.rbac = rbac
        logger.debug(_nbus_msg("nbus.debug.rbac"))

    async def initialize(self):
        logger.debug(_nbus_msg("nbus.debug.ready"))
        self._replay_task = asyncio.create_task(self._auto_replay_dlq())

        from adami_kernel.guardian.sensitive_filter import SensitiveFilter

        self.sensitive_filter = SensitiveFilter()
        self.add_middleware(self.sensitive_filter.middleware)
        logger.debug(_nbus_msg("nbus.debug.filter"))

        sink = get_trace_sink()
        await sink.start()
        self.add_middleware(sink.middleware)
        logger.debug(_nbus_msg("nbus.debug.sim_mw"))

        # Optional: clear DLQ once on boot to prevent RBAC/DLQ spam loops
        # (e.g. legacy events with disallowed `source_module`).
        if bool(getattr(settings, "ADAMI_DLQ_CLEAR_ON_BOOT", False)):
            dlq = getattr(self, "dlq_db", None)
            if dlq is not None and hasattr(dlq, "clear"):
                try:
                    await dlq.clear()
                    logger.warning(_nbus_msg("nbus.warn.dlq_cleared_on_boot"))
                except Exception:
                    # Best-effort only: never block boot.
                    pass

    # ====================== V4.7 系统事件白名单（本次 2.0 强化） ======================
    def _is_system_event(self, event: Any) -> bool:
        """内部系统事件跳过 RBAC 检查和 DLQ（白名单模式）"""
        trace = getattr(event, "trace_id", "")
        source = getattr(event, "source_module", "")

        # 系统模块白名单（覆盖所有内核模块 + 2.0 workflow）
        system_modules = (
            "peripheral.",
            "nexus.",
            "core.",
            "cortex.",
            "orchestrator.",
            "guardian.",
            "hippocampus.",
            "sensory.proprioception",
            "sensory.webhook",
            "sensory.base",
            "user.prompt",
            "workflow.",  # ← 2.0 新增：工作流事件白名单
        )

        # 系统 trace_id 前缀
        system_traces = ("circadian_", "boot_", "system.", "wf_")

        return any(trace.startswith(prefix) for prefix in system_traces) or any(
            source.startswith(prefix) for prefix in system_modules
        )

    # =================================================================================

    async def _auto_replay_dlq(self):
        while True:
            await asyncio.sleep(30)
            if not self.dlq_db or not hasattr(self.dlq_db, "pop_all"):
                continue

            try:
                dead_letters = await self.dlq_db.pop_all()
                if not dead_letters:
                    continue

                logger.debug(_nbus_msg("nbus.debug.dlq_found", n=len(dead_letters)))

                for ev_dict in dead_letters:
                    try:
                        retry_count = ev_dict.get("retry_count", 0) + 1
                        if retry_count > 5:
                            logger.warning(
                                _nbus_msg("nbus.warn.dlq_drop", tid=ev_dict.get("trace_id"))
                            )
                            continue

                        safe_dict = {
                            "trace_id": ev_dict.get("trace_id", "recovered"),
                            "source_module": ev_dict.get("source_module", "dlq"),
                            "target_topic": ev_dict.get("target_topic", "system.events"),
                            "priority": ev_dict.get("priority", EventPriority.NORMAL.value),
                            "payload": ev_dict.get("payload", {}),
                            "retry_count": retry_count,
                        }

                        ev = AdamiEvent(**safe_dict)
                        success = await self.publish(ev)

                        if not success:
                            logger.warning(
                                _nbus_msg("nbus.warn.dlq_fail", cur=retry_count, tid=ev.trace_id)
                            )

                    except Exception as e:
                        logger.error(_nbus_msg("nbus.err.dlq_deser", e=e))
            except Exception as e:
                logger.error(_nbus_msg("nbus.err.dlq_loop", e=e))

    def add_middleware(self, middleware: Callable[[Any], Awaitable[bool]]):
        self.middlewares.append(middleware)

    async def subscribe(self, topic: str) -> asyncio.Queue:
        q = asyncio.Queue()
        self.subscribers[topic].append(q)
        return q

    def _dump_event(self, event: Any) -> dict:
        if hasattr(event, "model_dump_json"):
            return json.loads(event.model_dump_json())
        elif hasattr(event, "dict"):
            return event.dict()
        return {"raw": str(event)}

    # ====================== 【Bug 2 核心修复 + 2.0 workflow 支持】 ======================
    async def publish(self, event: Any) -> bool:
        # V4.7 新增：系统事件直接放行（跳过 RBAC / 限流）
        if self._is_system_event(event):
            await offer_trace_event_for_system_path(event)
            if getattr(event, "target_topic", "") not in self.subscribers:
                return False
            success_count = 0
            for q in self.subscribers[event.target_topic]:
                try:
                    await asyncio.wait_for(q.put(event), timeout=0.5)
                    success_count += 1
                except asyncio.TimeoutError:
                    logger.warning(
                        _nbus_msg(
                            "nbus.warn.queue_full",
                            topic=event.target_topic,
                            tid=getattr(event, "trace_id", "unknown"),
                        )
                    )
                    if self.dlq_db:
                        await self.dlq_db.push(self._dump_event(event))
                except Exception as e:
                    logger.error(_nbus_msg("nbus.err.publish_sys", e=e))
            return success_count > 0

        # RBAC 权限检查
        if self.rbac is not None:
            source_module = getattr(event, "source_module", "unknown")
            target_topic = getattr(event, "target_topic", "unknown")
            if not self.rbac.check(source_module, target_topic):
                logger.warning(
                    _nbus_msg("nbus.warn.rbac_deny", src=source_module, topic=target_topic)
                )
                # RBAC DENY is not a transient failure: replaying via DLQ will only spam logs.
                # Drop the event without enqueuing to DLQ.
                return False

        # middleware
        for mw in self.middlewares:
            if not await mw(event):
                logger.warning(
                    _nbus_msg("nbus.warn.event_blocked", tid=getattr(event, "trace_id", "unknown"))
                )
                if self.dlq_db:
                    await self.dlq_db.push(self._dump_event(event))
                return False

        if getattr(event, "target_topic", "") not in self.subscribers:
            if self.dlq_db:
                await self.dlq_db.push(self._dump_event(event))
            return False

        success_count = 0
        for q in self.subscribers[event.target_topic]:
            try:
                await asyncio.wait_for(q.put(event), timeout=0.5)
                success_count += 1
            except asyncio.TimeoutError:
                logger.warning(
                    _nbus_msg(
                        "nbus.warn.queue_full",
                        topic=event.target_topic,
                        tid=getattr(event, "trace_id", "unknown"),
                    )
                )
                if self.dlq_db:
                    await self.dlq_db.push(self._dump_event(event))
            except Exception as e:
                logger.error(_nbus_msg("nbus.err.publish", e=e))

        return success_count > 0

    # =================================================================================


# --- END OF FILE bus.py ---
