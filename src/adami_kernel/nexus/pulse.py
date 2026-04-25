# --- START OF FILE pulse.py ---

import asyncio
import logging
from typing import TYPE_CHECKING, Awaitable, Callable, List, Optional

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t

if TYPE_CHECKING:
    # ====================== 【第五阶段新增】主动进化钩子 ======================
    from adami_kernel.skill_manager.skill_factory import SkillFactory
    from adami_kernel.skill_manager.skill_optimizer import SkillOptimizer
    from adami_kernel.skill_manager.skill_version_manager import SkillVersionManager
    # ==============================================================================

logger = logging.getLogger("NexusPulse")


def _puls_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class PulseTask:
    def __init__(self, name: str, interval_secs: int, task_func: Callable[[], Awaitable[None]]):
        self.name = name
        self.interval = interval_secs
        self.task_func = task_func
        self.last_run = 0


class AutonomicNervousSystem:
    """
    自主神经系统 (Pulse Module) - 工业级安全版
    负责驱动 AdamI 的主动节律，不依赖用户输入。
    【本次 5.3 核心增强】：skill_optimizer_scan 定时任务优先调用 SkillFactory.trigger_active_evolution 主动进化钩子
    """

    def __init__(self, bus_publish_func: Callable):
        self.publish = bus_publish_func
        self.tasks: List[PulseTask] = []
        self._running = False
        self.proprioception = None

        # ====================== 【第五阶段新增】SkillFactory 引用 ======================
        self.skill_factory: Optional["SkillFactory"] = None
        # ==============================================================================

    def set_proprioception(self, proprioception_sys):
        """提供显式的依赖注入接口，供 Kernel 调用"""
        self.proprioception = proprioception_sys
        logger.info(_puls_t("puls.log.proprio"))

    # ====================== 【第五阶段新增】注入 SkillFactory ======================
    def set_skill_factory(self, skill_factory: "SkillFactory") -> None:
        """动态注入 SkillFactory，实现主动进化钩子调用"""
        self.skill_factory = skill_factory
        logger.info(boot_t("boot.log.pulse_skill_factory_injected"))

    # ==============================================================================

    def register_rhythm(self, name: str, interval_secs: int, task_func: Callable):
        """注册一个定时节律"""
        self.tasks.append(PulseTask(name, interval_secs, task_func))
        logger.info(
            boot_t("boot.log.pulse_rhythm_registered", name=name, interval_secs=interval_secs)
        )

    def register_skill_optimizer(
        self,
        skill_version_manager: "SkillVersionManager",
        skill_optimizer: "SkillOptimizer",
        skill_factory: Optional["SkillFactory"] = None,
        interval_hours: int = 4,
    ) -> None:
        """
        注册技能自动优化节律（每 interval_hours 小时扫描一次）。
        【第五阶段增强】：优先使用 SkillFactory.trigger_active_evolution 主动进化钩子
        """
        interval_secs = interval_hours * 3600

        async def _optimize_needed_skills():
            """扫描并优化需要优化的技能（优先走主动进化钩子）"""
            try:
                # ====================== 【第五阶段优先路径】主动进化钩子 ======================
                if skill_factory:
                    logger.info(_puls_t("puls.log.active_evo"))
                    await skill_factory.trigger_active_evolution()
                # ==============================================================================

                # 版本管理器驱动的待优化列表（与主动进化钩子并行，不提前 return）
                skills = await skill_version_manager.get_skills_needing_optimization()
                if not skills:
                    logger.debug(_puls_t("puls.debug.optimize_none"))
                    return

                logger.info(
                    _puls_t(
                        "puls.log.optimize_found",
                        n=len(skills),
                        skills=str(skills),
                    )
                )

                semaphore = asyncio.Semaphore(
                    max(1, int(settings.ADAMI_ANS_SKILL_OPTIMIZE_MAX_PARALLEL))
                )

                async def _optimize_one(skill_name: str):
                    async with semaphore:
                        try:
                            result = await skill_optimizer.optimize(skill_name)
                            if result.get("status") == "success":
                                logger.info(
                                    _puls_t(
                                        "puls.log.optimize_ok",
                                        name=skill_name,
                                        ver=result.get("new_version"),
                                    )
                                )
                            else:
                                logger.warning(
                                    _puls_t(
                                        "puls.warn.optimize_fail",
                                        name=skill_name,
                                        reason=result.get("reason"),
                                    )
                                )
                        except Exception as e:
                            logger.error(
                                _puls_t("puls.err.optimize_exc", name=skill_name, e=e),
                                exc_info=True,
                            )

                await asyncio.gather(*[_optimize_one(name) for name in skills])

            except Exception as e:
                logger.error(_puls_t("puls.err.optimize_scan", e=e), exc_info=True)

        self.register_rhythm(
            name="skill_optimizer_scan",
            interval_secs=interval_secs,
            task_func=_optimize_needed_skills,
        )

    async def _safe_run(self, task: PulseTask):
        """安全包装器，防止协程异常静默吞没"""
        try:
            await task.task_func()
        except Exception as e:
            logger.error(
                _puls_t("puls.err.rhythm_crash", name=task.name, e=e),
                exc_info=True,
            )

    async def start(self):
        self._running = True
        logger.info(_puls_t("puls.log.activated"))

        while self._running:
            now = asyncio.get_event_loop().time()
            for task in self.tasks:
                actual_interval = task.interval
                if self.proprioception and getattr(
                    self.proprioception, "api_rate_limit_mode", False
                ):
                    actual_interval *= 5

                if now - task.last_run >= actual_interval:
                    logger.debug(
                        _puls_t(
                            "puls.debug.rhythm_tick",
                            name=task.name,
                            sec=actual_interval,
                        )
                    )
                    asyncio.create_task(self._safe_run(task))
                    task.last_run = now

            await asyncio.sleep(1.0)

    def stop(self):
        self._running = False


# --- END OF FILE pulse.py ---
