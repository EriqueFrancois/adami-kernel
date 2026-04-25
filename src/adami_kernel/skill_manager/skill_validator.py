# src/adami_kernel/skill_manager/skill_validator.py
# --- START OF FILE skill_validator.py ---
"""
AdamI Skill Manager - SkillValidator（独立严格验证器）

负责技能代码的多级验证（语法、导入、安全、签名、DreamSandbox 沙箱导入级试跑）。
验证完全前置于文件写入之前，符合单一职责原则。
【本次生产强化】：新增 validate 方法（兼容 SkillBuilder 调用），解决 AttributeError
【本次重构】：validate_all / validate_static 返回 ValidationResult 对象，支持上层精细化重试策略
【本次增强】：语法验证失败时记录更详细错误（行号 + 上下文代码行）
【本次修复】：签名验证正确识别 **kwargs（使用 node.args.kwarg）
【本次启用】：可选 DreamSandbox（Docker / 受限子进程）内执行 importlib 加载 + execute 可调用性检查
"""

from __future__ import annotations

import ast
import logging
import os
import uuid
from typing import TYPE_CHECKING, Optional, Tuple

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.skill_manager.skill_validation_result import ValidationResult

if TYPE_CHECKING:
    from adami_kernel.cortex.dream_sandbox import DreamSandbox

logger = logging.getLogger("AdamI-SkillValidator")


def _sv_t(key: str, **kwargs: object) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


def _log_validation_outcome(result: ValidationResult, skill_name: str) -> None:
    if result.passed:
        logger.info(_sv_t("skval.log.pass", name=skill_name))
    else:
        logger.warning(_sv_t("skval.warn.fail", name=skill_name, n=len(result.errors)))


class SkillValidator:
    """
    独立严格验证器
    静态方法用于语法/导入/签名；实例可选持有 DreamSandbox 以执行 ``validate_async`` 沙箱阶段。
    """

    def __init__(self, dream_sandbox: Optional[DreamSandbox] = None) -> None:
        self._dream_sandbox = dream_sandbox

    def validate(self, raw_code: str, skill_name: str) -> ValidationResult:
        """兼容 SkillBuilder / SkillWasher 的同步入口（不含异步沙箱；请优先使用 ``validate_async``）。"""
        logger.debug(_sv_t("skval.debug.start", name=skill_name))
        result = SkillValidator.validate_static(raw_code, skill_name)
        _log_validation_outcome(result, skill_name)
        return result

    @staticmethod
    def validate_all(raw_code: str, skill_name: str) -> ValidationResult:
        """与 ``validate_static`` 等价，保留旧名。"""
        return SkillValidator.validate_static(raw_code, skill_name)

    @staticmethod
    def validate_static(raw_code: str, skill_name: str) -> ValidationResult:
        """语法 + 导入安全 + 签名（无沙箱）。"""
        result = ValidationResult(passed=True)

        syntax_ok, syntax_info = SkillValidator.validate_syntax(raw_code)
        if not syntax_ok:
            message, line, context = syntax_info
            if context:
                full_msg = _sv_t("skill.validator.syntax_context", message=message, context=context)
            else:
                full_msg = message
            result.add_error(
                error_type="syntax",
                message=full_msg,
                line=line,
                suggestion=_sv_t("skill.validator.suggestion_syntax"),
            )

        import_ok, import_err = SkillValidator.validate_imports(raw_code)
        if not import_ok:
            result.add_error(
                error_type="security",
                message=import_err,
                suggestion=_sv_t("skill.validator.suggestion_security"),
            )

        sig_ok, sig_err = SkillValidator.validate_signature(raw_code)
        if not sig_ok:
            result.add_error(
                error_type="signature",
                message=sig_err,
                suggestion=_sv_t("skill.validator.suggestion_signature"),
            )

        return result

    async def validate_async(self, raw_code: str, skill_name: str) -> ValidationResult:
        """静态校验 + 可选 DreamSandbox 沙箱（在 ``build`` / ``wash`` 等异步上下文中调用）。"""
        logger.debug(_sv_t("skval.debug.start", name=skill_name))
        result = SkillValidator.validate_static(raw_code, skill_name)
        if not result.passed:
            _log_validation_outcome(result, skill_name)
            return result

        if not settings.ADAMI_SKILL_VALIDATOR_SANDBOX_ENABLED:
            logger.debug(_sv_t("skval.debug.sandbox_cfg_off", name=skill_name))
            _log_validation_outcome(result, skill_name)
            return result

        if self._dream_sandbox is None:
            logger.warning(_sv_t("skval.warn.sandbox_no_dream", name=skill_name))
            _log_validation_outcome(result, skill_name)
            return result

        ok, err = await self._run_sandbox_import_check(raw_code, skill_name)
        if not ok:
            result.passed = False
            result.add_error(
                error_type="sandbox",
                message=err,
                suggestion=_sv_t("skill.validator.suggestion_sandbox"),
            )

        _log_validation_outcome(result, skill_name)
        return result

    async def _run_sandbox_import_check(self, raw_code: str, skill_name: str) -> Tuple[bool, str]:
        """在 DreamSandbox 卷挂载路径写入临时技能文件，于容器/回退子进程中执行 importlib 加载检查。"""
        vol = getattr(self._dream_sandbox, "volume_path", None) or ""
        if not vol or not os.path.isdir(vol):
            return False, _sv_t("skval.err.sandbox_volume", path=str(vol))

        fname = f"_adami_val_{skill_name.lower()}_{uuid.uuid4().hex[:12]}.py"
        host_path = os.path.join(vol, fname)
        container_path = f"/sandbox/{fname}"

        try:
            with open(host_path, "w", encoding="utf-8") as f:
                f.write(raw_code)
        except OSError as e:
            return False, _sv_t("skval.err.sandbox_write", err=str(e))

        timeout = int(settings.ADAMI_SKILL_VALIDATOR_SANDBOX_TIMEOUT_SEC)
        # 在沙箱内只做「加载模块 + execute 可调用」，不调用 execute（避免副作用与参数耦合）
        py_src = (
            "import importlib.util\n"
            f"p = {container_path!r}\n"
            "spec = importlib.util.spec_from_file_location('_adami_val_skill', p)\n"
            "mod = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(mod)\n"
            "if not callable(getattr(mod, 'execute', None)):\n"
            "    raise RuntimeError('missing async def execute')\n"
        )
        cmd = ["python", "-c", py_src]

        try:
            logger.debug(_sv_t("skval.debug.sandbox_run", name=skill_name, path=container_path))
            report = await self._dream_sandbox.run_command_in_sandbox(cmd, timeout=timeout)
        except Exception as e:
            return False, _sv_t("skval.err.sandbox_exc", err=str(e))
        finally:
            try:
                if os.path.isfile(host_path):
                    os.unlink(host_path)
            except OSError:
                pass

        if report.get("status") == "timeout":
            return False, _sv_t("skval.err.sandbox_timeout", sec=timeout)
        if (report.get("status") or "") != "success":
            detail = (
                report.get("stderr") or report.get("stdout") or report.get("error") or ""
            ).strip()
            if len(detail) > 800:
                detail = detail[:800] + "…"
            return False, _sv_t(
                "skval.err.sandbox_cmd",
                rc=report.get("returncode"),
                detail=detail or str(report.get("status")),
            )
        return True, ""

    @staticmethod
    def validate_syntax(code: str) -> Tuple[bool, Tuple[str, Optional[int], str]]:
        """语法验证（ast.parse）——增强版：返回 (ok, (message, line, context))"""
        if not code.strip():
            return False, (_sv_t("skill.validator.empty_code"), None, "")
        try:
            ast.parse(code)
            return True, ("", None, "")
        except SyntaxError as e:
            line_num = e.lineno
            context = ""
            lines = code.splitlines()
            if line_num and 1 <= line_num <= len(lines):
                context = lines[line_num - 1].strip()
            return False, (_sv_t("skill.validator.ast_failed", detail=e.msg), line_num, context)

    @staticmethod
    def validate_imports(code: str) -> Tuple[bool, str]:
        """导入安全审计（复用原有危险关键字检查）"""
        dangerous = [
            "os.system",
            "subprocess.",
            "exec(",
            "eval(",
            "__import__",
            "open(",
            "shutil.",
            "pickle",
        ]
        for kw in dangerous:
            if kw in code:
                return False, _sv_t("skill.validator.dangerous", kw=kw)
        return True, ""

    @staticmethod
    def validate_signature(code: str) -> Tuple[bool, str]:
        """签名验证：必须存在 async def execute(**kwargs)"""
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef) and node.name == "execute":
                    if node.args.kwarg is not None:
                        return True, ""
                    if any(a.arg == "kwargs" for a in node.args.args):
                        return True, ""
                    return False, _sv_t("skill.validator.execute_kwargs")
            return False, _sv_t("skill.validator.execute_not_found")
        except Exception as e:
            return False, _sv_t("skill.validator.signature_parse", detail=str(e))

    @staticmethod
    def validate_sandbox(code: str, skill_name: str) -> Tuple[bool, str]:
        """同步占位：无事件循环时无法跑 DreamSandbox；请使用 ``SkillValidator(dream_sandbox).validate_async``。"""
        logger.debug(_sv_t("skval.debug.sandbox_sync_stub", name=skill_name))
        return True, ""
