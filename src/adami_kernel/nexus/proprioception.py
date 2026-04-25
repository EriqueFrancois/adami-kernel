import asyncio
import logging
import time
from typing import Awaitable, Callable

import psutil

from adami_kernel.config import settings
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.nexus.event import AdamiEvent, EventPriority

logger = logging.getLogger("AdamI-Proprioception")


def _prop_t(key: str, **kwargs: object) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class ProprioceptiveSystem:
    """
    本体感觉系统 (Proprioception & Homeostasis)
    负责感知宿主机的物理资源消耗，当系统资源濒临枯竭时，强制触发 URGENT 痛觉事件，
    并主动进行“冬眠节流”。已集成全局 429 Rate Limit 保护。
    """

    def __init__(self, publish_func: Callable[[AdamiEvent], Awaitable[None]]):
        self.publish = publish_func
        self._running = False

        # 物理痛觉阈值（已优化）
        self.critical_cpu_percent = 85.0
        self.critical_ram_percent = 90.0

        # 持续高危计数器
        self.cpu_danger_ticks = 0
        self.ram_danger_ticks = 0

        # 冷却与硅基供血监控
        self.last_pain_signal = 0
        self.api_rate_limit_mode = False  # ← 全局 429 节流标志

    async def start_monitoring(self):
        """启动本体感觉循环，这是比心跳自检更底层的潜意识扫描"""
        self._running = True
        logger.info(boot_t("boot.log.proprioception_started"))

        while self._running:
            try:
                # 当进入 API 节流模式时，自动延长检测间隔（降低负载）
                interval = 60.0 if self.api_rate_limit_mode else 5.0
                await asyncio.sleep(interval)
                await self._check_host_vitals()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(_prop_t("prop.log.sniff_fail", err=e))

    def stop(self):
        self._running = False

    async def toggle_api_starvation(self, is_starving: bool):
        """开启或关闭 API 节流模式（由 Router 在 429 时触发）
        【问题3 核心修复】：触发时强制休眠 60 秒，进入全局苟活模式
        """
        self.api_rate_limit_mode = is_starving
        if is_starving:
            logger.critical(_prop_t("prop.log.starve_on"))
            await asyncio.sleep(60)  # ← 强制节流 60 秒（防止连续 429 风暴）
            logger.warning(_prop_t("prop.log.starve_cool"))
        else:
            logger.info(_prop_t("prop.log.starve_off"))

    async def _check_host_vitals(self):
        """检查宿主生命体征"""
        cpu_usage = psutil.cpu_percent(interval=None)
        ram_usage = psutil.virtual_memory().percent

        # --- RAM 监控逻辑 (致命危机) ---
        if ram_usage > self.critical_ram_percent:
            self.ram_danger_ticks += 1
            if self.ram_danger_ticks >= 2:
                await self._trigger_physical_pain(
                    "RAM_EXHAUSTION",
                    _prop_t("prop.pain.ram", pct=ram_usage),
                )
                self.ram_danger_ticks = 0
        else:
            self.ram_danger_ticks = 0

        # --- CPU 监控逻辑 ---
        if cpu_usage > self.critical_cpu_percent:
            self.cpu_danger_ticks += 1
            if self.cpu_danger_ticks >= 5:
                await self._trigger_physical_pain(
                    "CPU_OVERHEATING",
                    _prop_t("prop.pain.cpu", pct=cpu_usage),
                )
                self.cpu_danger_ticks = 0
        else:
            self.cpu_danger_ticks = 0

    async def _trigger_physical_pain(self, pain_type: str, detail: str):
        """向大脑发送无法屏蔽的痛觉反射事件"""
        now = time.time()
        if now - self.last_pain_signal < 60:
            return

        self.last_pain_signal = now
        logger.critical(_prop_t("prop.log.pain", pain_type=pain_type))

        pain_event = AdamiEvent(
            trace_id=f"pain_{int(now)}",
            source_module="sensory.proprioception",
            target_topic="system.events",
            priority=EventPriority.URGENT,
            payload={
                "task": _prop_t("prop.event.task", detail=detail),
            },
        )
        await self.publish(pain_event)
