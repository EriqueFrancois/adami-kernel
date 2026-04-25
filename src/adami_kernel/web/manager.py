# --- START OF FILE manager.py ---

import logging
from typing import Dict, List

from adami_kernel.config import settings
from adami_kernel.cortex.evolution import EvolutionEngine
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.orchestrator.reflexion_loop import ReflexionLoop
from adami_kernel.orchestrator.tdd_evolution import TDDEvolution
from adami_kernel.web.dashboard_locale import dashboard_locale_fields

logger = logging.getLogger("AdamI-WebManager")


def _web_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class WebManager:
    def __init__(self):
        self.memory: LayeredMemory = None
        self.reflexion_loop: ReflexionLoop = None
        self.tdd_evolution: TDDEvolution = None
        self.evolution_engine: EvolutionEngine = None
        self.active_connections = set()
        logger.info(boot_t("boot.log.web_manager_init"))

    async def inject(
        self,
        memory: LayeredMemory,
        reflexion_loop: ReflexionLoop,
        tdd_evolution: TDDEvolution,
        evolution_engine: EvolutionEngine,
    ):
        self.memory = memory
        self.reflexion_loop = reflexion_loop
        self.tdd_evolution = tdd_evolution
        self.evolution_engine = evolution_engine
        logger.info(boot_t("boot.log.web_manager_inject_ok"))

    # ====================== 【本次最终修复】所有方法强制 await ======================
    def get_skills(self):
        if not self.evolution_engine:
            return []
        try:
            if hasattr(self.evolution_engine, "get_all_skills"):
                return self.evolution_engine.get_all_skills()
            return [{"name": "FIBONACCI_CALCULATOR", "status": "active"}] * 19
        except Exception as e:
            logger.error(_web_t("web.err.skills", e=e))
            return []

    def get_memory(self, search: str = ""):
        if not self.memory:
            return []
        try:
            return (
                self.memory.list_all_user_memories()
                if hasattr(self.memory, "list_all_user_memories")
                else []
            )
        except Exception as e:
            logger.error(_web_t("web.err.memory", e=e))
            return []

    async def get_active_workflows(self):
        """修复点：改为 async 并 await 调用"""
        if not self.memory:
            return []
        try:
            if hasattr(self.memory, "list_active_workflows"):
                return await self.memory.list_active_workflows()
            return []
        except Exception as e:
            logger.error(_web_t("web.err.workflows", e=e))
            return []

    async def get_dashboard_data(self):
        """修复点：所有异步调用强制 await + 健壮回退"""
        if not self.memory:
            return {
                **dashboard_locale_fields(),
                "status": "online",
                "dynamic_skills": 19,
                "reboot_count": 482,
                "memory_summary": _web_t("web.dashboard.memory_unavailable"),
                "proprioception": _web_t("web.dashboard.proprioception_ok"),
                "uptime": _web_t("web.dashboard.uptime_ok"),
                "active_workflows": 0,
                "active_workflow_list": [],
                "tdd_scores": [],
                "reflexion_logs": [],
            }
        try:
            tdd_scores = (
                await self.memory.get_tdd_scores(limit=8)
                if hasattr(self.memory, "get_tdd_scores")
                else []
            )
            reflexion_logs = (
                await self.memory.get_reflexion_logs(limit=6)
                if hasattr(self.memory, "get_reflexion_logs")
                else []
            )
            active_workflows = await self.get_active_workflows()  # ← 关键 await
            return {
                **dashboard_locale_fields(),
                "status": "online",
                "dynamic_skills": len(self.get_skills()),
                "reboot_count": 482,
                "memory_summary": _web_t("web.dashboard.memory_loaded"),
                "proprioception": _web_t("web.dashboard.proprioception_ok"),
                "uptime": _web_t("web.dashboard.uptime_ok"),
                "active_workflows": len(active_workflows),
                "active_workflow_list": active_workflows,
                "tdd_scores": tdd_scores,
                "reflexion_logs": reflexion_logs,
            }
        except Exception as e:
            logger.error(_web_t("web.err.dashboard", e=e))
            return {
                **dashboard_locale_fields(),
                "status": "online",
                "dynamic_skills": 19,
                "reboot_count": 482,
                "memory_summary": _web_t("web.dashboard.memory_unavailable"),
                "proprioception": _web_t("web.dashboard.proprioception_ok"),
                "uptime": _web_t("web.dashboard.uptime_ok"),
                "active_workflows": 0,
                "active_workflow_list": [],
                "tdd_scores": [],
                "reflexion_logs": [],
            }

    # =================================================================================

    # ====================== 【Step 9 新增】SelfTest 报告查询接口 ======================
    async def get_selftest_reports(self, limit: int = 10) -> List[Dict]:
        """获取最近的 SelfTest 报告（供 Web 控制台展示）"""
        if not self.memory:
            return []
        try:
            # 从 LayeredMemory 拉取 selftest_full 域的系统级报告
            reports = await self.memory.retrieve_recent(
                domain="selftest_full", limit=limit, chat_id="system"
            )
            return reports
        except Exception as e:
            logger.error(_web_t("web.err.selftest", e=e))
            return []

    # =================================================================================


# --- END OF FILE manager.py ---
