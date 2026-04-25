# src/adami_kernel/peripheral/circadian_nerve.py
# --- START OF FILE circadian_nerve.py ---

import asyncio
import glob
import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from rich.console import Console

from adami_kernel.config import settings
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.nexus.event import AdamiEvent, EventPriority

logger = logging.getLogger("AdamI-Circadian")
console = Console()


def _circ_t(key: str, **kwargs: object) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class CircadianNerve:
    """
    AdamI 生物钟神经 V2.6 (高能效工业版)
    【修复】：彻底消除了每 10 秒唤醒一次的死循环。改为精准计算距离次日 9:00 的秒数并进入深度睡眠。
    【优化】：增加错失补偿机制。
    【修复】：chat_id 统一转为字符串，与 DecisionProcessor 期望类型一致。
    【本次核心增强】：每日晨会前执行深度垃圾回收（Deep GC），清理长期堆积的沙箱测试文件、临时技能文件等。
    """

    def __init__(self, event_bus: Any, default_chat_id: int = 5405872526):
        self.event_bus = event_bus
        self.default_chat_id = default_chat_id
        self._running = False
        self._last_daily_trigger_date = None
        self.tz_bjt = timezone(timedelta(hours=8))  # 北京时间
        # 模块五：last30days 定时触发退避（仅记录触发时间；执行成败由上层技能路径决定）
        self._last30days_last_trigger_ts: dict[str, float] = {}
        self._last30days_last_publish_error_ts: dict[str, float] = {}

    def _should_trigger_last30days(
        self, key: str, *, now_ts: float, min_interval_sec: float
    ) -> bool:
        """退避：同 key 在最小间隔内只触发一次；若刚 publish 报错则加倍冷却。"""
        last = self._last30days_last_trigger_ts.get(key)
        if last is not None and now_ts - last < min_interval_sec:
            return False
        last_err = self._last30days_last_publish_error_ts.get(key)
        if last_err is not None and now_ts - last_err < min_interval_sec * 2:
            return False
        return True

    async def _publish_last30days_digest_event(
        self,
        *,
        now: datetime,
        topic: str,
        digest_kind: str,
        emit: str = "context",
        write_to: str = "Inbox",
        sources: str = "auto",
        refresh: bool = False,
    ) -> None:
        """
        发布一个“请求执行 last30days digest”的系统事件。

        注意：当前系统主通路是把 payload.task 交给 DecisionProcessor/Planner；
        因此这里用明确的“强约束指令”引导其调用工具 LAST30DAYS_DIGEST。
        """
        args_json = json.dumps(
            {
                "topic": topic,
                "refresh": bool(refresh),
                "emit": emit,
                "write_to": write_to,
                "sources": sources,
            },
            ensure_ascii=False,
        )
        task_content = _circ_t(
            "circ.last30.task",
            digest_kind=digest_kind,
            date=now.strftime("%Y-%m-%d"),
            topic=topic,
            args_json=args_json,
        )
        event = AdamiEvent(
            trace_id=f"circadian_last30days_{digest_kind}_{int(now.timestamp())}",
            source_module="peripheral.circadian",
            target_topic="system.events",
            priority=EventPriority.HIGH,
            payload={"task": task_content, "chat_id": str(self.default_chat_id)},
        )
        try:
            await self.event_bus.publish(event)
        except Exception as e:
            self._last30days_last_publish_error_ts[digest_kind] = now.timestamp()
            logger.warning("[CircadianNerve] last30days publish failed kind=%s: %s", digest_kind, e)
            return
        self._last30days_last_trigger_ts[digest_kind] = now.timestamp()

    async def start(self):
        if self._running:
            return
        self._running = True
        console.print(f"[bold yellow]{boot_t('boot.circadian_activated')}[/bold yellow]")
        asyncio.create_task(self._tick())

    async def stop(self):
        self._running = False
        console.print(f"[dim yellow]{boot_t('boot.circadian_stopped')}[/dim yellow]")

    def _get_seconds_until_next_9am(self, now: datetime) -> float:
        """计算距离下一个 09:00:00 还有多少秒"""
        target = now.replace(hour=9, minute=0, second=0, microsecond=0)
        if now >= target:
            # 如果今天的时间已经过了 9 点，则计算到明天的 9 点
            target += timedelta(days=1)
        return (target - now).total_seconds()

    async def _deep_garbage_collection(self):
        """【深度GC】清理各类废弃临时文件（仅删除超过24小时的文件）"""
        directories_to_clean = [
            settings.path_temp_skills_dir,
            settings.path_failed_skills_dir,
            settings.path_sandbox_tests_dir,
        ]
        total_freed = 0
        now = time.time()
        for dir_path in directories_to_clean:
            if os.path.exists(dir_path):
                try:
                    for f in glob.glob(os.path.join(dir_path, "*")):
                        if os.path.isfile(f) and os.stat(f).st_mtime < now - 86400:  # 24小时前
                            os.remove(f)
                            total_freed += 1
                except Exception as e:
                    logger.warning(_circ_t("circ.gc.dir_fail", dir_path=dir_path, err=e))

        if total_freed > 0:
            logger.info(_circ_t("circ.gc.done", n=total_freed))
        else:
            logger.debug(_circ_t("circ.gc.nothing"))

    async def _tick(self):
        while self._running:
            try:
                now = datetime.now(self.tz_bjt)

                # 容错：如果机器在 09:00 到 09:05 之间刚启动，且今天还没触发过，立即补发
                if now.hour == 9 and 0 <= now.minute <= 5:
                    if self._last_daily_trigger_date != now.date():
                        self._last_daily_trigger_date = now.date()
                        await self._trigger_morning_routine(now)

                # 精确计算距离下一次 09:00 的秒数
                sleep_seconds = self._get_seconds_until_next_9am(datetime.now(self.tz_bjt))

                # 深度休眠，期间不占用任何 CPU 资源
                # 为了防止休眠时间过长导致系统状态变更无法响应，最多切片为每小时唤醒一次做内部检查
                max_sleep_slice = 3600.0
                while sleep_seconds > 0 and self._running:
                    slice_to_sleep = min(sleep_seconds, max_sleep_slice)
                    await asyncio.sleep(slice_to_sleep)
                    sleep_seconds -= slice_to_sleep

                # 休眠结束，时间到达，触发晨会
                if self._running:
                    now = datetime.now(self.tz_bjt)
                    if self._last_daily_trigger_date != now.date():
                        self._last_daily_trigger_date = now.date()
                        await self._trigger_morning_routine(now)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(_circ_t("circ.tick.error", err=e))
                await asyncio.sleep(60)  # 异常后冷却1分钟继续

    async def _trigger_morning_routine(self, now: datetime, is_test: bool = False):
        # 1. 触发前置文件垃圾回收（深度GC）
        await self._deep_garbage_collection()

        prefix = (
            _circ_t("circ.morning.prefix.test") if is_test else _circ_t("circ.morning.prefix.daily")
        )
        console.print(_circ_t("circ.morning.console", prefix=prefix))

        task_content = _circ_t(
            "circ.morning.task",
            prefix=prefix,
            date=now.strftime("%Y-%m-%d"),
        )

        # 【修复】将 chat_id 转换为字符串，与 DecisionProcessor 期望类型一致
        event = AdamiEvent(
            trace_id=f"circadian_{int(now.timestamp())}",
            source_module="peripheral.circadian",
            target_topic="system.events",
            priority=EventPriority.HIGH,
            payload={"task": task_content, "chat_id": str(self.default_chat_id)},
        )

        try:
            await self.event_bus.publish(event)
        except Exception as e:
            console.print(_circ_t("circ.publish.fail_console", err=e))

        # ====================== 模块五：last30days 外部世界简报触发（可选） ======================
        try:
            enabled = bool(getattr(settings, "ADAMI_LAST30DAYS_ENABLED", False))
            daily_topic = (getattr(settings, "ADAMI_LAST30DAYS_DAILY_TOPIC", None) or "").strip()
            weekly_topic = (getattr(settings, "ADAMI_LAST30DAYS_WEEKLY_TOPIC", None) or "").strip()
            write_to = (
                str(getattr(settings, "ADAMI_LAST30DAYS_WRITE_TO", "Inbox") or "Inbox").strip()
                or "Inbox"
            )
            emit = (
                str(getattr(settings, "ADAMI_LAST30DAYS_EMIT_MODE", "context") or "context").strip()
                or "context"
            )
            refresh_default = bool(getattr(settings, "ADAMI_LAST30DAYS_REFRESH_DEFAULT", False))
        except Exception as e:
            logger.warning("[CircadianNerve] last30days settings parse failed: %s", e)
            enabled = False
            daily_topic = ""
            weekly_topic = ""
            write_to = "Inbox"
            emit = "context"
            refresh_default = False

        if enabled and daily_topic:
            key = "daily"
            if self._should_trigger_last30days(
                key, now_ts=now.timestamp(), min_interval_sec=3600.0
            ):
                await self._publish_last30days_digest_event(
                    now=now,
                    topic=daily_topic,
                    digest_kind=key,
                    emit=emit,
                    write_to=write_to,
                    sources="auto",
                    refresh=refresh_default,
                )

        # 周报：默认周一（weekday=0）09:00 触发；依赖 weekly_topic 非空
        if enabled and weekly_topic and now.weekday() == 0:
            key = "weekly"
            if self._should_trigger_last30days(
                key, now_ts=now.timestamp(), min_interval_sec=6 * 3600.0
            ):
                await self._publish_last30days_digest_event(
                    now=now,
                    topic=weekly_topic,
                    digest_kind=key,
                    emit=emit,
                    write_to=write_to,
                    sources="auto",
                    refresh=refresh_default,
                )


# --- END OF FILE src/adami_kernel/peripheral/circadian_nerve.py ---
