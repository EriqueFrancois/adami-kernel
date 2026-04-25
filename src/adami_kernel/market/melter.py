# --- START OF FILE melter.py ---

from __future__ import annotations

import ast
import json
import logging
import re
import textwrap
from typing import TYPE_CHECKING, Optional

from adami_kernel.i18n.boot_msg import boot_t

logger = logging.getLogger("AdamI-SkillMelter")

if TYPE_CHECKING:
    from adami_kernel.cortex.evolution import EvolutionEngine


class SkillMelter:
    """
    AdamI 技能熔炼引擎（工业级代码清洗 + 适配器）
    已彻底修复 f-string 嵌套导致的 bad escape 错误
    改进：自动检测代码是否已包含 async def execute，避免重复包装。
    """

    def __init__(self, evolution_engine: EvolutionEngine):
        self.evolution = evolution_engine

        self.forbidden_patterns = [
            r"os\.system",
            r"os\.popen",
            r"subprocess\.(call|Popen|run|check_output)",
            r"eval\s*\(",
            r"exec\s*\(",
            r"__import__\s*\(",
            r'open\s*\(\s*["\']',
            r"sys\.exit",
        ]

        logger.info(boot_t("boot.log.skill_melter_ready"))

    async def melt(self, raw_code: str, skill_name: str) -> Optional[str]:
        """核心熔炼方法：自动检测代码结构，决定是否包装；失败返回 None"""
        if not raw_code or not isinstance(raw_code, str):
            logger.error(boot_t("boot.log.melter_empty_or_non_string"))
            return None

        logger.info(boot_t("boot.log.melter_start", name=skill_name, length=len(raw_code)))

        # 1. 清理危险代码
        cleaned = self._remove_dangerous_code(raw_code)
        # 2. 转换同步代码为异步（如 requests -> httpx, time.sleep -> asyncio.sleep）
        cleaned = self._convert_sync_to_async(cleaned)

        # 3. 检测是否已包含 async def execute 函数
        if self._has_async_execute(cleaned):
            logger.info(boot_t("boot.log.melter_has_execute", name=skill_name))
            if not self._validate_code(cleaned):
                logger.error(boot_t("boot.log.melter_raw_syntax_error", name=skill_name))
                return None
            return cleaned

        # 4. 未包含 async def execute，使用模板包装
        # 对用户代码的花括号做转义（防止 f-string 冲突）
        cleaned = cleaned.replace("{", "{{").replace("}", "}}")

        final_code = self._wrap_into_skill_template(cleaned, skill_name)

        if not self._validate_code(final_code):
            logger.error(boot_t("boot.log.melter_post_syntax_error", name=skill_name))
            return None

        logger.info(boot_t("boot.log.melter_success", name=skill_name, length=len(final_code)))
        return final_code

    def _has_async_execute(self, code: str) -> bool:
        pattern = r"async\s+def\s+execute\s*\("
        if re.search(pattern, code):
            return True
        try:
            tree = ast.parse(code)
            for node in ast.walk(tree):
                if isinstance(node, ast.AsyncFunctionDef) and node.name == "execute":
                    return True
        except SyntaxError:
            pass
        return False

    def _remove_dangerous_code(self, code: str) -> str:
        for pattern in self.forbidden_patterns:
            code = re.sub(
                pattern, "# [MELTED] Forbidden pattern removed", code, flags=re.IGNORECASE
            )
        return code

    def _convert_sync_to_async(self, code: str) -> str:
        replacements = {
            r"import requests": "import httpx",
            r"requests\.get": "await httpx.AsyncClient().get",
            r"requests\.post": "await httpx.AsyncClient().post",
            r"time\.sleep": "await asyncio.sleep",
        }
        for old, new in replacements.items():
            code = re.sub(old, new, code, flags=re.IGNORECASE)
        return code

    def _wrap_into_skill_template(self, core_logic: str, skill_name: str) -> str:
        """使用普通字符串 + .format()，并正确缩进核心逻辑"""
        # 将核心逻辑缩进 8 个空格（try 块内）
        indented_logic = textwrap.indent(core_logic, "        ")
        melter_doc = boot_t("cjk_gate.melter_execute_docline", skill_name=skill_name)
        success_literal = json.dumps(boot_t("cjk_gate.melter_success_payload"))
        template = f'''import asyncio
import json
import logging
import httpx
import os
from typing import Dict, Any

logger = logging.getLogger("AdamI-Skill-{skill_name}")

async def execute(*args_tuple, **kwargs) -> Dict[str, Any]:
    """{melter_doc}"""
    args = {{}}
    for a in args_tuple:
        if isinstance(a, dict): args.update(a)
        elif isinstance(a, str):
            try:
                parsed = json.loads(a)
                if isinstance(parsed, dict): args.update(parsed)
            except: pass
    args.update(kwargs)

    try:
        # --- melted skill core ---
{indented_logic}
        # --- end melted core ---
        # default success if user code returns nothing
        return {{"status": "success", "data": {success_literal}, "error": None}}
    except Exception as e:
        logger.error("execute failed: " + str(e))
        return {{"status": "error", "data": None, "error": str(e)}}
'''
        return template.format(skill_name=skill_name, indented_logic=indented_logic)

    def _validate_code(self, code: str) -> bool:
        try:
            ast.parse(code)
            return True
        except SyntaxError as e:
            logger.error(boot_t("boot.log.melter_wrap_syntax_error", detail=str(e)))
            return False

    async def close(self):
        pass


# --- END OF FILE melter.py ---
