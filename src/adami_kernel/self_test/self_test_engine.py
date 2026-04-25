# src/adami_kernel/self_test/self_test_engine.py
"""
AdamI 2.0 runtime SelfTest 引擎（工业级自我验证进化核心）

核心功能：在梦境沙箱中安全运行 pytest 测试套件，实现“失败后先自测 → 确认根因 → 再自愈”的闭环。
【本次 Step 4 核心修复】：集成 config 开关 + 精确 status 区分（error / failed / success）
【本次最终优化】：run_critical_tests 和 run_full_test_suite 完全从 settings 读取文件列表
【步骤1 核心重构】：SelfTest 完全异步后置化，由 SkillBuilder 的 _schedule_background_tdd 后台任务调用，不再阻塞主链路
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

# ====================== 【Step 4 核心集成】引入配置和 SelfTestRunner ======================
from adami_kernel.config import settings
from adami_kernel.cortex.dream_sandbox import DreamSandbox
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.nexus.bus import EventBus
from adami_kernel.self_test.self_test_runner import SelfTestRunner
from adami_kernel.web.observability import observability

# =================================================================================

logger = logging.getLogger("AdamI-SelfTestEngine")


def _steng_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class SelfTestEngine:
    """
    AdamI 2.0 runtime SelfTest 引擎（工业级自我验证进化核心）
    【步骤1 重构】：现在仅作为后台异步任务执行，不再阻塞 SkillBuilder 主链路
    """

    def __init__(self, memory: LayeredMemory, bus: EventBus, dream_sandbox: DreamSandbox):
        self.memory = memory
        self.bus = bus
        self.dream_sandbox = dream_sandbox
        self.test_dir = os.path.abspath("tests")

        # ====================== 【集成】SelfTestRunner ======================
        self.runner = SelfTestRunner()
        # =======================================================================

        logger.info(boot_t("boot.log.self_test_engine_init"))

    async def initialize(self):
        """初始化 SelfTest 引擎"""
        if not os.path.exists(self.test_dir):
            logger.warning(_steng_t("steng.warn.no_tests_dir", path=self.test_dir))
        else:
            logger.info(boot_t("boot.log.self_test_tests_ready", path=self.test_dir))

        # ====================== 【集成】安全初始化 runner ======================
        if hasattr(self.runner, "initialize") and asyncio.iscoroutinefunction(
            self.runner.initialize
        ):
            await self.runner.initialize()
        else:
            logger.warning(_steng_t("steng.warn.runner_compat"))
        # =======================================================================

    # ====================== 【Step 4 新增】配置开关判断 ======================
    def _should_run_self_test(self) -> bool:
        """根据配置决定是否执行 SelfTest"""
        enabled = getattr(settings, "ADAMI_ENABLE_SELF_TEST", True)
        if not enabled:
            logger.debug(_steng_t("steng.debug.disabled"))
        return enabled

    # =======================================================================

    # ====================== 【本次核心优化】使用配置项 ======================
    async def run_critical_tests(
        self, workflow_id: str = None, chat_id: str = None
    ) -> Dict[str, Any]:
        """关键路径测试（ReflexionLoop 失败后立即调用）"""
        if not self._should_run_self_test():
            return {"status": "disabled", "pass_rate": 1.0}

        async with observability.start_span(
            span_name="selftest.critical", workflow_id=workflow_id, chat_id=chat_id
        ):
            logger.info(_steng_t("steng.log.critical_start", wid=workflow_id or ""))

            # 从配置读取（带 fallback）
            test_files = getattr(
                settings,
                "ADAMI_SELF_TEST_CRITICAL_FILES",
                ["test_workflow_engine.py", "test_reflexion.py"],
            )

            report = await self._run_pytest_in_sandbox(test_files=test_files, timeout=60)
            await self._persist_test_report("critical", report, workflow_id, chat_id)
            return report

    async def run_full_test_suite(self, chat_id: str = None) -> Dict[str, Any]:
        """全量测试（MetaCortex 定期巡检）"""
        if not self._should_run_self_test():
            return {"status": "disabled", "pass_rate": 1.0}

        async with observability.start_span(span_name="selftest.full_suite", chat_id=chat_id):
            logger.info(_steng_t("steng.log.full_start"))

            # 从配置读取（带 fallback）
            test_files = getattr(
                settings,
                "ADAMI_SELF_TEST_FULL_FILES",
                [
                    "test_workflow_engine.py",
                    "test_multi_agent.py",
                    "test_reflexion.py",
                    "test_tdd.py",
                    "test_evolution.py",
                ],
            )

            report = await self._run_pytest_in_sandbox(test_files=test_files, timeout=120)
            await self._persist_test_report("full", report, None, chat_id)
            return report

    # =======================================================================

    # ====================== 【Step 4 增强】精确状态区分 ======================
    async def _run_pytest_in_sandbox(
        self, test_files: List[str], timeout: int = 60
    ) -> Dict[str, Any]:
        """在 DreamSandbox 中安全执行 pytest + 精确状态区分"""
        report = await self.runner.run_pytest(test_files, timeout)

        if report.get("error"):
            report["status"] = "error"
            report["pass_rate"] = 0.0
        else:
            # 根据通过率判断状态
            report["status"] = "success" if report.get("pass_rate", 0) == 1.0 else "failed"

        return report

    # =======================================================================

    async def _persist_test_report(
        self,
        test_type: str,
        report: Dict[str, Any],
        workflow_id: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        """持久化 SelfTest 报告到 LayeredMemory"""
        domain = f"selftest_{test_type}_{chat_id}" if chat_id else f"selftest_{test_type}"
        payload = {
            "test_type": test_type,
            "report": report,
            "workflow_id": workflow_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        await self.memory.store_experience(
            trace_id=f"selftest_{test_type}_{int(datetime.now().timestamp())}",
            domain=domain,
            payload=payload,
            chat_id=chat_id,
        )
        logger.info(_steng_t("steng.log.report_saved", domain=domain))

    async def shutdown(self):
        logger.info(_steng_t("steng.log.shutdown"))
        if hasattr(self, "runner") and self.runner and hasattr(self.runner, "shutdown"):
            await self.runner.shutdown()


# --- END OF FILE src/adami_kernel/self_test/self_test_engine.py ---
