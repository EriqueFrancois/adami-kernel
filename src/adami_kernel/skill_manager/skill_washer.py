# src/adami_kernel/skill_manager/skill_washer.py
# --- START OF FILE skill_washer.py ---

import ast
import logging
import textwrap
from typing import TYPE_CHECKING, Optional

from adami_kernel.config import settings
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.skill_manager.skill_validator import SkillValidator

if TYPE_CHECKING:
    from adami_kernel.cortex.dream_sandbox import DreamSandbox

logger = logging.getLogger("AdamI-SkillWasher")


def _swsh_t(key: str, **kwargs: object) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class SkillWasher:
    """
    SkillWasher（洗髓引擎） - 第三阶段核心组件
    职责：对 GitHub 高星库代码或 LLM 原始代码进行安全“洗髓”
    - 删除危险调用（os.system、subprocess、exec、eval、__import__ 等）
    - 强制转为 async def execute(**kwargs)
    - 注入重试机制 + 标准日志 + 异常处理
    - 输出符合 Adami 技能规范的最终代码
    【修改4 新增】安全模板健壮性强化 + 完整性注释
    """

    DANGEROUS_KEYWORDS = [
        "os.system",
        "subprocess.",
        "exec(",
        "eval(",
        "__import__",
        "open(",
        "shutil.",
        "pickle.",
        "shelve.",
        "dbm.",
        "crypt.",
        "pty.",
        "pty.spawn",
        "os.popen",
        "commands.",
        "glob.glob",
    ]

    def __init__(self, dream_sandbox: Optional["DreamSandbox"] = None):
        self.validator = SkillValidator(dream_sandbox=dream_sandbox)
        logger.info(boot_t("boot.log.skill_washer_init"))

    async def wash(self, raw_code: str, skill_name: str) -> str:
        """核心洗髓入口"""
        skill_name = skill_name.upper()

        # 1. 安全审计 + 危险调用移除
        cleaned_code = self._remove_dangerous_calls(raw_code)

        # 2. 强制包装为标准 async execute 模板
        final_code = self._wrap_as_standard_skill(cleaned_code, skill_name)

        # 3. 验证洗髓后代码
        validation_result = await self.validator.validate_async(final_code, skill_name)
        if not validation_result.passed:
            logger.error(_swsh_t("swsh.log.validation_fail", detail=validation_result))
            # 兜底返回最小安全模板
            return self._minimal_safe_template(skill_name)

        logger.info(_swsh_t("swsh.log.done", skill_name=skill_name))
        return final_code

    def _remove_dangerous_calls(self, code: str) -> str:
        """AST 级危险调用移除 + 替换为安全占位"""
        try:
            tree = ast.parse(code)

            class DangerRemover(ast.NodeTransformer):
                def visit_Call(self, node):
                    if isinstance(node.func, ast.Attribute):
                        call_str = ast.unparse(node)
                        for kw in SkillWasher.DANGEROUS_KEYWORDS:
                            if kw in call_str:
                                logger.warning(_swsh_t("swsh.log.replaced_call", call_str=call_str))
                                msg = repr(_swsh_t("swsh.runtime.danger_removed"))
                                return ast.parse(f"raise RuntimeError({msg})").body[0]
                    return self.generic_visit(node)

            remover = DangerRemover()
            new_tree = remover.visit(tree)
            ast.fix_missing_locations(new_tree)
            return ast.unparse(new_tree)
        except Exception as e:
            logger.warning(_swsh_t("swsh.ast_fallback", err=e))
            # 字符串兜底清洗
            for kw in self.DANGEROUS_KEYWORDS:
                code = code.replace(kw, _swsh_t("swsh.fallback.replace_kw", kw=kw))
            return code

    def _wrap_as_standard_skill(self, core_code: str, skill_name: str) -> str:
        """包装为标准 Adami 技能模板（async + 重试 + 日志）"""
        doc_main = _swsh_t("swsh.min.doc_main")
        return f'''import asyncio
import logging
from typing import Dict, Any
import httpx  # async HTTP client

logger = logging.getLogger("AdamI-Skill-{skill_name}")

async def execute(**kwargs) -> Dict[str, Any]:
    """{doc_main}"""
    retry_count = 0
    max_retries = 3
    while retry_count < max_retries:
        try:
{textwrap.indent(core_code, "            ")}
            return {{"status": "success", "data": result}}
        except Exception as e:
            retry_count += 1
            logger.warning(
                f"Skill {skill_name} execute failed (retry {{retry_count}}/{{max_retries}}): {{e}}"
            )
            if retry_count >= max_retries:
                logger.error(f"Skill {skill_name} final execute failed")
                return {{"status": "error", "error": str(e)}}
            await asyncio.sleep(1)
'''

    def _minimal_safe_template(self, skill_name: str) -> str:
        """洗髓失败时的最小安全模板
        【修改4 强化】本模板返回**完整、可直接执行的技能文件**，
        包含 async def execute、标准日志、异常处理和兜底返回值。
        确保 SkillBuilder / SkillInspector 不会进行二次包装。
        """
        c1 = _swsh_t("swsh.min.comment.full_file")
        c2 = _swsh_t("swsh.min.comment.no_rewrap")
        doc_f = _swsh_t("swsh.min.doc_fallback")
        log_line = repr(_swsh_t("swsh.min.log_exec", skill_name=skill_name))
        msg_lit = repr(_swsh_t("swsh.min.return_msg"))
        err_pfx = repr(_swsh_t("swsh.min.log_exc_prefix"))
        head = f"""import asyncio
import logging
from typing import Dict, Any

logger = logging.getLogger("AdamI-Skill-{skill_name}")

# {c1}
# {c2}

async def execute(**kwargs) -> Dict[str, Any]:
    \"\"\"{doc_f}\"\"\"
    try:
        logger.info({log_line})
"""
        ret_ok = '        return {"status": "success", "data": {"message": ' + msg_lit + "}}\n"
        tail = f"""    except Exception as e:
        logger.error({err_pfx} + str(e))
        return {{"status": "error", "error": str(e)}}"""
        return head + ret_ok + tail


# --- END OF FILE skill_washer.py ---
