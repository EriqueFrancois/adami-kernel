# --- START OF FILE tdd_evolution.py ---

import logging
import re
from typing import Any, Dict

from adami_kernel.config import settings
from adami_kernel.cortex.dream_sandbox import DreamSandbox
from adami_kernel.cortex.evolution import EvolutionEngine
from adami_kernel.cortex.router import LLMRouter
from adami_kernel.hippocampus.episodic_memory import EpisodicMemory
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.nexus.proprioception import ProprioceptiveSystem  # 用于内存/CPU 监控

# ====================== 【阶段4 新增】OpenTelemetry Span 覆盖 ======================
from adami_kernel.web.observability import observability

# =================================================================================

logger = logging.getLogger("AdamI-TDDEvolution")


class TDDEvolution:
    """
    AdamI 2.0 TDD 技能进化引擎（工业级测试驱动固化机制）
    核心功能：强制 LLM 输出 test_case 块 → 沙箱执行 → 多维打分 → 固化/降级
    得分 < 0.8 的技能视为残次品，仅记录教训；>= 0.8 的技能固化到 instincts 并推入 SkillMarket
    【本次核心修复】：_generate_test_case 增加多级 fallback 提取机制，提升 LLM 输出格式容错性
    """

    def __init__(
        self,
        evolution_engine: EvolutionEngine,
        dream_sandbox: DreamSandbox,
        memory: LayeredMemory,
        episodic_memory: EpisodicMemory,
        proprioception: ProprioceptiveSystem = None,
        router: LLMRouter = None,
    ):  # ← router 参数（kernel.py 后续注入）
        self.evolution_engine = evolution_engine
        self.dream_sandbox = dream_sandbox
        self.memory = memory
        self.episodic_memory = episodic_memory
        self.proprioception = proprioception
        self.router = router
        self.min_score_threshold = 0.8
        logger.info("[TDDEvolution] ready")

    def _loc(self) -> str:
        return settings.effective_ui_default_locale()

    async def create_skill_with_tdd(
        self, task_description: str, research_summary: str = ""
    ) -> Dict[str, Any]:
        """
        强制 TDD 流程创建新技能
        返回最终技能信息 + 得分报告
        """
        async with observability.start_span(
            span_name="tdd.create_skill_with_tdd",
            attributes={
                "task_description": task_description[:200],
                "research_summary": research_summary[:200],
            },
        ):
            logger.info(
                boot_t(
                    "boot.log.tdd_create_start",
                    preview=task_description[:80],
                )
            )

            try:
                # 1. 生成带测试用例的技能代码（强制 LLM 输出 test_case 块）
                skill_result = await self.evolution_engine.create_new_skill(
                    task_description=task_description,
                    research_summary=research_summary,
                    force_tdd=False,
                )

                # 2. 提取主代码和测试用例
                main_code = skill_result.get("code", "")
                test_case_block = skill_result.get("test_case", "")

                # ========== 【核心修复】TDD 测试用例缺失时自动补充 ==========
                if not test_case_block:
                    logger.warning(boot_t("boot.log.tdd_missing_test_case"))
                    test_case_block = await self._generate_test_case(main_code, task_description)
                    if not test_case_block:
                        logger.warning(boot_t("boot.log.tdd_gen_test_fail_reflexion"))
                        await self._trigger_reflexion_for_missing_test(task_description)
                        return {"status": "failed", "reason": "missing_test_case_after_retry"}
                # =================================================================

                # 3. 沙箱试炼（主代码 + 测试用例）
                sandbox_report = await self.dream_sandbox.run_tdd_test(main_code, test_case_block)

                # 4. 多维打分
                score = self._calculate_tdd_score(sandbox_report)

                # 4.1 写入 Dashboard 数据源（tdd_scores）
                # Dashboard /api/tdd_scores 读取 LayeredMemory.get_tdd_scores()，因此这里必须落盘
                skill_name_for_score = skill_result.get("skill_name", "auto_tdd_skill")
                try:
                    await self.memory.save_tdd_score(
                        skill_name=skill_name_for_score,
                        score=float(score),
                        report=sandbox_report,
                        chat_id="system",
                    )
                except Exception as e:
                    logger.warning(boot_t("boot.log.tdd_write_scores_fail", detail=str(e)))

                # 5. 决策：固化 or 降级
                if score >= self.min_score_threshold:
                    skill_name = skill_name_for_score
                    await self.evolution_engine.melt_and_solidify(skill_name, main_code)
                    await self.memory.store_experience(
                        trace_id=f"tdd_success_{skill_name}",
                        domain="tdd_evolution_log",
                        payload={
                            "skill_name": skill_name,
                            "score": score,
                            "report": sandbox_report,
                        },
                        chat_id="system",
                    )
                    logger.info(
                        boot_t(
                            "boot.log.tdd_solidified",
                            name=skill_name,
                            score=score,
                        )
                    )
                    return {
                        "status": "solidified",
                        "skill_name": skill_name,
                        "score": score,
                        "report": sandbox_report,
                    }
                else:
                    await self.episodic_memory.save_error(
                        task_description,
                        "CREATE_NEW_SKILL_TDD",
                        "{}",
                        i18n_t(
                            "tdd_evolution.episodic_score_below",
                            locale=self._loc(),
                            score=score,
                            threshold=self.min_score_threshold,
                        ),
                    )
                    logger.warning(boot_t("boot.log.tdd_score_low", score=score))
                    return {"status": "defective", "score": score, "report": sandbox_report}

            except Exception as e:
                logger.error(boot_t("boot.log.tdd_create_failed", detail=str(e)))
                return {"status": "failed", "reason": str(e)}

    # ====================== 【本次核心修复】多级 fallback 提取测试用例 ======================
    async def _generate_test_case(self, code: str, task_description: str) -> str:
        """调用 LLM 根据主代码和任务描述生成测试用例（带多级 fallback）"""
        if not self.router:
            logger.warning(boot_t("boot.log.tdd_router_missing"))
            return ""

        prompt = i18n_t(
            "tdd_evolution.generate_test_prompt",
            locale=self._loc(),
            task_description=task_description,
            code=code,
        )

        try:
            response = await self.router.call_llm(prompt, brain_type="action", temperature=0.2)

            # 1. 优先提取 ```python test_case ... ```
            match = re.search(
                r"```python\s*test_case\s*(.*?)```", response, re.DOTALL | re.IGNORECASE
            )
            if match:
                test_case = match.group(1).strip()
                if test_case and "assert" in test_case:
                    logger.info(boot_t("boot.log.tdd_extract_block", length=len(test_case)))
                    return test_case

            # 2. 提取普通 ```python ... ``` 块，并检查是否包含 assert
            match = re.search(r"```python\s*(.*?)```", response, re.DOTALL | re.IGNORECASE)
            if match:
                test_case = match.group(1).strip()
                if "assert" in test_case:
                    logger.info(boot_t("boot.log.tdd_extract_python", length=len(test_case)))
                    return test_case

            # 3. 最后尝试从文本中直接提取包含 assert 的行
            lines = response.splitlines()
            test_lines = [line for line in lines if "assert" in line.lower()]
            if test_lines:
                test_case = "\n".join(test_lines)
                logger.info(boot_t("boot.log.tdd_extract_lines", n=len(test_lines)))
                return test_case

            logger.warning(boot_t("boot.log.tdd_no_test_extracted"))
            return ""
        except Exception as e:
            logger.error(boot_t("boot.log.tdd_generate_exception", detail=str(e)))
            return ""

    # =================================================================

    def _calculate_tdd_score(self, report: Dict[str, Any]) -> float:
        """多维打分板"""
        pass_rate = report.get("pass_rate", 0.0)
        time_score = 1.0 - (report.get("execution_time", 1.0) / 5.0)
        mem_score = 1.0 - (report.get("peak_memory_mb", 100.0) / 500.0)
        score = 0.5 * pass_rate + 0.3 * max(0.0, time_score) + 0.2 * max(0.0, mem_score)
        return max(0.0, min(1.0, score))

    async def _trigger_reflexion_for_missing_test(self, task_description: str):
        """缺失 test_case 时触发 Reflexion"""
        async with observability.start_span(
            span_name="tdd.trigger_reflexion_for_missing_test",
            attributes={"task_description": task_description[:200]},
        ):
            await self.episodic_memory.save_error(
                task_description,
                "CREATE_NEW_SKILL_TDD",
                "{}",
                i18n_t("cjk_gate.tdd_no_test_case_block", locale=self._loc()),
            )


# --- END OF FILE tdd_evolution.py ---
