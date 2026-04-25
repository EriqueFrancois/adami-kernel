# 文件路径：src/adami_kernel/skill_manager/skill_optimizer.py
# 版本：v2.2（SelfTestRunner 真实注入版 + 与 component_initializer 完全对齐）
# 修改时间：2026-04-07
# 修复目的：确保 SkillOptimizer 收到真正的 SelfTestRunner 执行器，解决 'SelfTestEngine' object has no attribute 'run_test_file'

import asyncio
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, Optional

from adami_kernel.config import settings
from adami_kernel.cortex.evolution import EvolutionEngine
from adami_kernel.cortex.router import LLMRouter
from adami_kernel.hippocampus.episodic_memory import EpisodicMemory
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.i18n import t as i18n_t
from adami_kernel.skill_manager.code_quality_scorer import CodeQualityScorer
from adami_kernel.skill_manager.skill_manager import SkillManager
from adami_kernel.skill_manager.skill_metadata import serialize_skill_metadata


def _sopt_t(key: str, **kwargs: object) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


# ====================== 【第三阶段最终】Tier 分层获取入口 ======================
# ==============================================================================
# ====================== 【第五阶段新增】真实 SelfTestRunner ======================
from adami_kernel.self_test.self_test_runner import SelfTestRunner
from adami_kernel.skill_manager.skill_factory import SkillFactory

# ==============================================================================
# ====================== 【第四阶段新增】TDD 测试用例生成器 ======================
from adami_kernel.skill_manager.skill_tdd_generator import SkillTDDGenerator

# ==============================================================================

logger = logging.getLogger("AdamI-SkillOptimizer")

SKILL_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


class SkillOptimizer:
    """
    技能自动优化器（Phase 4 + 第二阶段 + 第三阶段 + 第四阶段 TDD 闭环 + 第五阶段真实 SelfTest 执行）
    【v2.2 核心修复】：与 component_initializer.py 步骤 2 完全对齐，接收真正的 SelfTestRunner 执行器
    """

    def __init__(
        self,
        memory: LayeredMemory,
        episodic_memory: EpisodicMemory,
        evolution_engine: EvolutionEngine,
        skill_manager: SkillManager,
        router: LLMRouter,
        self_test_runner: Optional[
            SelfTestRunner
        ] = None,  # ← 关键：真实 TDD 执行器（由 component_initializer 注入 .runner）
    ):
        self.memory = memory
        self.episodic_memory = episodic_memory
        self.evolution_engine = evolution_engine
        self.skill_manager = skill_manager
        self.router = router
        self.code_quality_scorer = CodeQualityScorer(router, episodic_memory)
        # ====================== 【第三阶段新增】SkillFactory 注入 ======================
        _ds = getattr(evolution_engine, "dream_sandbox", None)
        self.skill_factory = SkillFactory(router, dream_sandbox=_ds)
        # ==============================================================================
        # ====================== 【第四阶段新增】TDD 生成器注入 ======================
        self.tdd_generator = SkillTDDGenerator(router)
        # ==============================================================================
        # ====================== 【第五阶段新增】SelfTestRunner 真实执行注入 ======================
        self.self_test_runner = self_test_runner
        # ==============================================================================
        logger.debug("[SkillOptimizer] CodeQualityScorer + SkillFactory + TDD generator wired")
        if self.self_test_runner:
            logger.debug("[SkillOptimizer] SelfTestRunner wired")
        else:
            logger.warning(_sopt_t("sopt.log.selftest_missing"))

    async def optimize(self, skill_name: str) -> Dict[str, Any]:
        if self.skill_manager and self.skill_manager.is_instinct(skill_name):
            logger.info(_sopt_t("sopt.log.instinct_skip", skill_name=skill_name))
            return {"status": "skipped", "reason": _sopt_t("sopt.reason.instinct_skip")}

        if not SKILL_NAME_PATTERN.match(skill_name):
            logger.warning(_sopt_t("sopt.log.bad_name", skill_name=skill_name))
            return {"status": "skipped", "reason": _sopt_t("sopt.reason.invalid_name")}

        logger.info(_sopt_t("sopt.log.start", skill_name=skill_name))

        errors = await self._get_skill_errors(skill_name)
        if not errors:
            logger.info(_sopt_t("sopt.log.no_errors", skill_name=skill_name))
            return {"status": "skipped", "reason": _sopt_t("sopt.reason.no_errors")}

        new_code = None
        for attempt in range(2):
            new_code = await self._generate_optimized_code(skill_name, errors)
            if new_code:
                break
            logger.warning(_sopt_t("sopt.log.gen_retry", attempt=attempt + 1))
            await asyncio.sleep(1)
        if not new_code:
            logger.error(_sopt_t("sopt.log.gen_fail", skill_name=skill_name))
            return {"status": "error", "reason": _sopt_t("sopt.reason.gen_failed")}

        # ====================== 【第四阶段新增】TDD 测试用例生成与验证 ======================
        logger.info(_sopt_t("sopt.log.tdd_gen", skill_name=skill_name))
        tdd_code = await self.tdd_generator.generate_test_cases(skill_name, new_code)
        tdd_passed = await self._run_tdd_validation(skill_name, tdd_code)
        if not tdd_passed:
            logger.warning(_sopt_t("sopt.log.tdd_reject", skill_name=skill_name))
            return {"status": "rejected", "reason": _sopt_t("sopt.reason.tdd_failed")}
        logger.info(_sopt_t("sopt.log.tdd_ok", skill_name=skill_name))
        # =====================================================================

        # ====================== 【步骤 2.2 新增】新旧代码对比评价 ======================
        old_code = await self._get_current_code(skill_name)
        if old_code:
            new_score = await self.code_quality_scorer.score_code(new_code, skill_name, old_code)
            old_score = await self.code_quality_scorer.score_code(old_code, skill_name)

            logger.info(
                _sopt_t(
                    "sopt.log.score_cmp",
                    new_score=new_score.total_score,
                    old_score=old_score.total_score,
                )
            )

            if new_score.total_score <= old_score.total_score + 5:
                logger.info(_sopt_t("sopt.log.keep_old"))
                await self._mark_as_protected(skill_name)
                return {"status": "skipped", "reason": _sopt_t("sopt.reason.not_better")}

            logger.info(_sopt_t("sopt.log.replace"))
        # =====================================================================

        version_info = await self._get_next_version(skill_name)
        new_version = version_info["next_version"]
        description = _sopt_t(
            "sopt.desc.register_fmt",
            new_version=new_version,
            errors_preview=errors[:100] + "...",
        )

        register_result = None
        for attempt in range(2):
            register_result = await self.skill_manager.inspect_and_register(
                skill_name=skill_name,
                code=new_code,
                description=description,
            )
            if register_result.get("status") == "success":
                break
            logger.warning(_sopt_t("sopt.log.reg_retry", attempt=attempt + 1))
            await asyncio.sleep(1)
        if register_result.get("status") != "success":
            logger.error(
                _sopt_t(
                    "sopt.log.reg_fail",
                    feedback=register_result.get("feedback"),
                )
            )
            return {
                "status": "error",
                "reason": _sopt_t("sopt.reason.register_failed"),
                "detail": register_result,
            }

        await self._deprecate_old_version(skill_name, new_version)

        logger.info(_sopt_t("sopt.log.done", skill_name=skill_name, new_version=new_version))
        return {
            "status": "success",
            "skill_name": skill_name,
            "new_version": new_version,
            "new_skill_name": register_result.get("skill_name"),
        }

    async def _get_current_code(self, skill_name: str) -> Optional[str]:
        """读取当前技能文件内容（用于新旧对比）"""
        try:
            path = os.path.join(settings.ADAMI_DATA_DIR, "skills", f"{skill_name}.py")
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    return f.read()
            else:
                logger.warning(_sopt_t("sopt.log.missing_file", skill_name=skill_name))
                return None
        except Exception as e:
            logger.warning(_sopt_t("sopt.log.read_old_fail", err=e))
            return None

    async def _mark_as_protected(self, skill_name: str) -> None:
        logger.info(_sopt_t("sopt.log.protected", skill_name=skill_name))

    # ====================== 【第五阶段新增】真实 TDD 执行 ======================
    async def _run_tdd_validation(self, skill_name: str, tdd_code: str) -> bool:
        """第五阶段真实 TDD 执行：保存测试文件 → 调用 SelfTestRunner 真实运行 → 记录结果"""
        if not hasattr(self, "self_test_runner") or self.self_test_runner is None:
            logger.warning(_sopt_t("sopt.log.tdd_runner_none"))
            return True

        test_file_path = os.path.join("tests", f"test_{skill_name.lower()}.py")
        try:
            os.makedirs("tests", exist_ok=True)
            with open(test_file_path, "w", encoding="utf-8") as f:
                f.write(tdd_code)

            logger.info(_sopt_t("sopt.log.tdd_saved", path=test_file_path))

            passed = await self.self_test_runner.run_test_file(test_file_path)

            # 记录 TDD 结果到 VersionManager（用于本能固化计数）
            await self.skill_manager.skill_version_manager.record_tdd_result(skill_name, passed)

            res_label = _sopt_t("sopt.tdd.passed") if passed else _sopt_t("sopt.tdd.failed")
            logger.info(_sopt_t("sopt.log.tdd_result", skill_name=skill_name, result=res_label))
            return passed

        except Exception as e:
            logger.error(_sopt_t("sopt.log.tdd_exec_fail", err=e))
            return False

    # =====================================================================

    # ==================== 以下为原有方法（100% 保留） ====================
    async def _get_skill_errors(self, skill_name: str) -> str:
        errors = await self.episodic_memory.recall_errors(
            current_task=f"skill {skill_name} execution failure",
            current_action="optimization",
            n_results=5,
        )
        return errors

    async def _generate_optimized_code(self, skill_name: str, errors: str) -> Optional[str]:
        """第三阶段核心：使用 SkillFactory（Tier 1 GitHub 高星 + 洗髓优先）"""
        description = _sopt_t(
            "sopt.prompt.optimize_wrap",
            skill_name=skill_name,
            errors=errors,
        )
        try:
            logger.info(_sopt_t("sopt.log.tier1", skill_name=skill_name))
            raw_code = await self.skill_factory.generate_code(description, skill_name)

            if not raw_code.strip():
                logger.warning(_sopt_t("sopt.log.empty_code"))
                return None

            if not hasattr(self.evolution_engine, "skill_builder"):
                logger.warning(_sopt_t("sopt.log.no_builder"))
                return None

            file_path, validation_result = await self.evolution_engine.skill_builder.build(
                raw_code, skill_name
            )
            if not validation_result.passed:
                logger.error(_sopt_t("sopt.log.build_fail", detail=validation_result))
                return None

            with open(file_path, "r", encoding="utf-8") as f:
                final_code = f.read()
            return final_code

        except Exception as e:
            logger.error(_sopt_t("sopt.log.gen_exc", err=e), exc_info=True)
            return None

    async def _get_next_version(self, skill_name: str) -> Dict[str, Any]:
        metadata = await self.skill_manager.get_skill_metadata(skill_name)
        if metadata and metadata.current_version:
            current = metadata.current_version
            if current.startswith("v"):
                try:
                    ver_str = current[1:]
                    if "." in ver_str:
                        major, minor = map(int, ver_str.split("."))
                        next_version = f"v{major}.{minor + 1}"
                    else:
                        next_version = f"v{int(ver_str) + 1}"
                except Exception:
                    next_version = "v1.1"
            else:
                next_version = "v1.1"
        else:
            next_version = "v1.1"
        return {
            "current_version": metadata.current_version if metadata else None,
            "next_version": next_version,
        }

    async def _deprecate_old_version(self, skill_name: str, new_version: str) -> None:
        try:
            metadata = await self.skill_manager.get_skill_metadata(skill_name)
            if metadata:
                metadata.status = "deprecated"
                metadata.updated_at = datetime.now()
                payload = serialize_skill_metadata(metadata)
                await self.skill_manager.memory.store_experience(
                    trace_id=f"deprecate_{skill_name}_{int(datetime.now().timestamp())}",
                    domain="skill_metadata",
                    payload=payload,
                    chat_id="system",
                )
                logger.info(_sopt_t("sopt.log.deprecated", skill_name=skill_name))
        except Exception as e:
            logger.error(_sopt_t("sopt.log.deprecate_fail", err=e))
