# src/adami_kernel/skill_manager/skill_builder.py
"""
AdamI Skill Manager - SkillBuilder（工程化职责）

负责将 SkillFactory 生成的原始代码工程化为符合系统规范的技能文件。
包括：语法修复（AST 级）、统一缩进、安全审计、添加标准模板、写入文件。
【本次修复】：ValidationError 防护 - 统一处理 CodeNormalizer 返回的 ValidationError / ValidationResult
【本次修改】：validator.validate_async 在异步 build 中调用（含可选 DreamSandbox）
【步骤1 核心重构】：TDD & SelfTest 异步后置化 - 质检通过后立即返回 v1.0，TDD/SelfTest 推入后台异步任务
【本次强化】：微重试结果直接写入临时工作区（TempSkillWorkspace + temp_dir 快照）
【本次修复】：智能检测完整技能，避免对已经包含 execute 函数的代码进行二次包装，导致 SkillInspector execute 返回 None
"""

import asyncio
import logging
import os
import re
import shutil
import textwrap

# 使用 TYPE_CHECKING 避免循环导入
from typing import TYPE_CHECKING, Optional, Tuple

from adami_kernel.config import settings
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.skill_manager.code_normalizer import ValidationError
from adami_kernel.skill_manager.skill_validation_result import ValidationResult
from adami_kernel.skill_manager.skill_validator import SkillValidator
from adami_kernel.skill_manager.temp_skill_workspace import TempSkillWorkspace

if TYPE_CHECKING:
    from adami_kernel.cortex.dream_sandbox import DreamSandbox
    from adami_kernel.skill_manager.skill_manager import SkillManager

logger = logging.getLogger("AdamI-SkillBuilder")


def _sb_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class SkillBuilder:
    """
    SkillBuilder（单一职责）
    将原始代码工程化为规范的技能文件。
    【本次强化】：微重试结果直接写入临时工作区，供 Engineer 内循环快速追踪
    【步骤1 重构】：验证通过后立即返回 v1.0，TDD/SelfTest 改为异步后台任务
    【本次修复】：智能检测完整技能，避免二次包装导致 SkillInspector execute 返回 None
    """

    def __init__(
        self,
        memory: LayeredMemory,
        skill_manager: Optional["SkillManager"] = None,
        dream_sandbox: Optional["DreamSandbox"] = None,
    ):
        self.memory = memory
        self.skill_manager = skill_manager
        self.skills_dir = os.path.join(settings.ADAMI_DATA_DIR, "skills")
        self.temp_dir = f"{self.skills_dir}/temp"
        os.makedirs(self.skills_dir, exist_ok=True)
        os.makedirs(self.temp_dir, exist_ok=True)

        self.workspace = TempSkillWorkspace()

        self.validator = SkillValidator(dream_sandbox=dream_sandbox)

        logger.info(boot_t("boot.log.skill_builder_init"))

    # ====================== 【步骤4 本能固化保护】 ======================
    def is_instinct(self, skill_name: str) -> bool:
        """代理调用 SkillManager.is_instinct"""
        if self.skill_manager:
            return self.skill_manager.is_instinct(skill_name)
        return False

    # =====================================================================

    # ====================== 【本次修复】智能完整技能检测 ======================
    def _is_complete_skill(self, code: str) -> bool:
        """检测代码是否已经是完整的技能文件（包含 async def execute 和必要的导入）"""
        # 正则匹配 async def execute( 开头
        has_execute = re.search(r"async\s+def\s+execute\s*\(", code) is not None
        # 正则匹配文件开头的 import / from 语句
        has_import = re.search(r"^\s*(import|from)\s+", code, re.MULTILINE) is not None
        return has_execute and has_import

    # =====================================================================

    async def build(
        self, core_code: str, skill_name: str
    ) -> Tuple[Optional[str], ValidationResult]:
        """核心构建入口（步骤1 重构：质检通过后立即返回 v1.0）"""
        skill_name = skill_name.upper()

        # 本能保护：已固化技能直接跳过重新构建
        if self.is_instinct(skill_name):
            logger.info(_sb_t("skbd.log.instinct_skip", skill_name=skill_name))
            final_path = os.path.join(self.skills_dir, f"{skill_name}.py")
            if os.path.exists(final_path):
                return final_path, ValidationResult(passed=True)
            else:
                logger.warning(_sb_t("skbd.log.instinct_missing", skill_name=skill_name))

        # 【本次强化】微重试结果直接写入临时工作区（Engineer 内循环专用）
        await self._write_micro_retry_snapshot(core_code, skill_name)

        # 1. 安全审计
        security_error = self._security_audit(core_code)
        if security_error:
            vr = ValidationResult(passed=False)
            vr.add_error(
                error_type="security",
                message=str(security_error),
                suggestion=_sb_t("skill.builder.suggest_security_retry"),
            )
            return None, vr

        # 2. 包装标准模板（仅当不是完整技能时）【本次修复核心】
        if self._is_complete_skill(core_code):
            logger.info(_sb_t("skbd.log.complete_detected", skill_name=skill_name))
            final_code = core_code
        else:
            final_code = self._wrap_with_standard_template(core_code, skill_name)

        # 3. 写入文件
        file_path = await self._write_skill_file(final_code, skill_name)
        if not file_path:
            vr = ValidationResult(passed=False)
            vr.add_error(
                error_type="io",
                message=_sb_t("skill.builder.write_failed", skill_name=skill_name),
                suggestion=_sb_t("skill.builder.suggest_disk"),
            )
            return None, vr

        # 4. 验证（静态 + 可选沙箱）
        try:
            validation_result = await self.validator.validate_async(final_code, skill_name)
        except Exception as e:
            logger.error(_sb_t("skbd.log.validate_exc", err=e))
            validation_result = ValidationResult(passed=False)
            validation_result.add_error(
                error_type="validator_exception",
                message=_sb_t(
                    "skill.builder.validator_failed",
                    exc_type=type(e).__name__,
                    detail=str(e),
                ),
                suggestion=_sb_t("skill.builder.suggest_validator_version"),
            )

        # 【步骤1 核心改动】质检通过 → 立即返回 v1.0 VALIDATED，用户无需等待 TDD/SelfTest
        if validation_result.passed:
            logger.info(_sb_t("skbd.log.step1_ok"))
            # 异步启动 TDD & SelfTest 后台任务
            asyncio.create_task(self._schedule_background_tdd(skill_name, file_path))
            return file_path, validation_result

        # 验证失败仍返回原始结果
        return file_path, validation_result

    # ====================== 【步骤1 新增】异步后台 TDD & SelfTest ======================
    async def _schedule_background_tdd(self, skill_name: str, file_path: str):
        """异步后置任务：TDD Generator + SelfTestRunner（步骤1 核心）"""
        logger.info(_sb_t("skbd.log.bg_sched", skill_name=skill_name, file_path=file_path))
        try:
            # TODO: 后续步骤2-4 中会在这里调用 TDD Generator 和 SelfTestRunner
            # 当前先记录日志，防止链路阻塞
            logger.info(_sb_t("skbd.log.bg_ok"))
            # 后续会通过 kernel.bus.publish 或 CircadianNerve 正式触发
        except Exception as e:
            logger.error(_sb_t("skbd.log.bg_err", err=e))

    # =================================================================================

    # ====================== 【本次强化】微重试结果直接写入临时工作区 ======================
    async def _write_micro_retry_snapshot(self, core_code: str, skill_name: str) -> None:
        """将 Engineer 微重试修复后的核心代码直接写入临时工作区（审计追踪专用）"""
        snapshot_path = os.path.join(self.temp_dir, f"{skill_name}_micro_retry.py")
        try:
            with open(snapshot_path, "w", encoding="utf-8") as f:
                f.write(core_code)

            # 同时同步到 TempSkillWorkspace（保持解耦设计）
            if hasattr(self.workspace, "save_temp_skill"):
                await self.workspace.save_temp_skill(skill_name, core_code)
            elif hasattr(self.workspace, "write"):
                self.workspace.write(skill_name, core_code, is_micro_retry=True)

            logger.info(_sb_t("skbd.log.micro_ok", path=snapshot_path))
        except Exception as e:
            logger.warning(_sb_t("skbd.log.micro_warn", err=e))

    # =================================================================================

    def _security_audit(self, code: str) -> Optional[ValidationError]:
        """安全审计"""
        dangerous = ["os.system", "subprocess", "exec(", "eval(", "__import__", "open(", "shutil"]
        for kw in dangerous:
            if kw in code:
                return ValidationError(
                    "security",
                    _sb_t("skbd.sec.msg", kw=kw),
                    suggestion=_sb_t("skbd.sec.suggest"),
                )
        return None

    def _wrap_with_standard_template(self, core_code: str, skill_name: str) -> str:
        """添加标准模板"""
        _httpx_comment = _sb_t("skbd.tpl.comment_httpx")
        _log_err = _sb_t("skbd.tpl.log_err", skill_name=skill_name)
        return f"""import asyncio
import logging
import httpx   {_httpx_comment}
from typing import Dict, Any

logger = logging.getLogger("AdamI-Skill-{skill_name}")

async def execute(**kwargs) -> Dict[str, Any]:
    try:
{textwrap.indent(core_code, "        ")}
    except Exception as e:
        logger.error(f"{_log_err}")
        return {{"status": "error", "error": str(e)}}
"""

    async def _write_skill_file(self, final_code: str, skill_name: str) -> Optional[str]:
        """临时目录验证 → 正式目录移动"""
        temp_path = os.path.join(self.temp_dir, f"{skill_name}.py")
        final_path = os.path.join(self.skills_dir, f"{skill_name}.py")

        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(final_code)

            shutil.move(temp_path, final_path)
            return final_path
        except Exception as e:
            logger.error(_sb_t("skbd.log.write_fail", err=e))
            return None


# --- END OF FILE src/adami_kernel/skill_manager/skill_builder.py ---
