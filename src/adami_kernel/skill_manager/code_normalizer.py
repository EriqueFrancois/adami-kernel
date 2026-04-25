# --- START OF FILE code_normalizer.py ---
"""
AdamI Skill Manager - CodeNormalizer（代码规范器）

替代旧 SkillCodeCleaner，专注于使代码语法正确，不改变语义。
严格遵循重构建议：ast.parse → unparse + 常见修复 fallback。
"""

import ast
import logging
import re
import textwrap
from dataclasses import dataclass
from typing import Optional, Tuple

from adami_kernel.i18n.boot_msg import boot_t

logger = logging.getLogger("AdamI-CodeNormalizer")


@dataclass
class ValidationError:
    """结构化验证错误（供 SkillBuilder / Engineer 使用）"""

    error_type: str  # "syntax" | "indent" | "bracket" | "quote"
    message: str
    line: Optional[int] = None
    column: Optional[int] = None
    context: Optional[str] = None
    suggestion: Optional[str] = None


class CodeNormalizer:
    """
    代码规范器（单一职责）
    使原始代码语法正确、缩进统一。
    """

    @staticmethod
    def normalize(raw_code: str) -> Tuple[str, Optional[ValidationError]]:
        """
        主入口：规范化代码
        返回：(规范化后的代码, None) 或 (原代码, ValidationError)
        """
        if not raw_code or not raw_code.strip():
            return "", ValidationError("empty", boot_t("cjk_gate.code_normalizer_empty"))

        # 1. 先尝试 ast.parse + unparse（最彻底的缩进统一方式）
        try:
            tree = ast.parse(raw_code)
            normalized = ast.unparse(tree)  # Python 3.9+ 官方重新生成（缩进统一）
            logger.debug(boot_t("boot.log.code_normalizer_ast_unparse_ok"))
            return normalized, None
        except SyntaxError as e:
            logger.warning(
                boot_t(
                    "boot.log.code_normalizer_first_ast_fail",
                    line=e.lineno or 0,
                    detail=str(e),
                )
            )
            # 进入 fallback 修复
            return CodeNormalizer._fallback_fix(raw_code, e)

    @staticmethod
    def _fallback_fix(
        raw_code: str, original_error: SyntaxError
    ) -> Tuple[str, Optional[ValidationError]]:
        """常见修复 + 二次验证（增强版缩进修复，保护多行字符串）"""
        fixed = raw_code

        # 修复1：制表符 → 4空格
        fixed = fixed.replace("\t", "    ")

        # 修复2：统一缩进（先 dedent 再 indent）
        fixed = textwrap.dedent(fixed)
        fixed = textwrap.indent(fixed, "    ")

        # 修复3：常见括号/引号不匹配
        fixed = re.sub(r"“|”|‘|’", '"', fixed)  # 全角引号
        fixed = re.sub(r"（", "(", fixed)
        fixed = re.sub(r"）", ")", fixed)
        fixed = re.sub(r"，", ",", fixed)  # 全角逗号

        # 修复4：高级缩进修复（保护多行字符串）
        fixed = CodeNormalizer._fix_indentation_safe(fixed)

        # 二次 AST 验证
        try:
            ast.parse(fixed)
            logger.debug(boot_t("boot.log.code_normalizer_fallback_ok"))
            return fixed, None
        except SyntaxError as e2:
            logger.error(
                boot_t(
                    "boot.log.code_normalizer_all_fixes_failed",
                    line=e2.lineno or 0,
                    detail=str(e2),
                )
            )
            # 尝试记录失败代码以便调试
            return fixed, ValidationError(
                error_type="syntax",
                message=boot_t("cjk_gate.code_normalizer_ast_fail", detail=e2.msg or ""),
                line=e2.lineno,
                column=e2.offset,
                context=raw_code.splitlines()[e2.lineno - 1] if e2.lineno else None,
                suggestion=boot_t("cjk_gate.code_normalizer_syntax_hint"),
            )

    @staticmethod
    def _fix_indentation_safe(code: str) -> str:
        """
        安全缩进修复：逐行分析，但跳过多行字符串内部的行，避免破坏字符串内容。
        确保所有行使用一致的缩进风格（空格），并根据上下文调整。
        """
        lines = code.splitlines()
        if not lines:
            return code

        # 第一步：移除所有空行的前导空格（保持空行干净）
        lines = [line if line.strip() else "" for line in lines]

        # 多行字符串状态跟踪
        in_multiline_string = False
        multiline_delimiter = None  # '"""' 或 "'''"

        # 第二步：逐行处理，跳过多行字符串内部
        processed_lines = []
        i = 0
        while i < len(lines):
            line = lines[i]
            stripped = line.lstrip()
            if not stripped:
                processed_lines.append(line)
                i += 1
                continue

            # 检测多行字符串开始或结束
            if not in_multiline_string:
                # 检查是否以 """ 或 ''' 开头（可能前面有空格）
                # 注意：字符串可能在同一行开始和结束，如 """..."""
                if stripped.startswith('"""'):
                    in_multiline_string = True
                    multiline_delimiter = '"""'
                    # 检查是否在同一行结束
                    if stripped.count('"""') >= 2:
                        in_multiline_string = False
                elif stripped.startswith("'''"):
                    in_multiline_string = True
                    multiline_delimiter = "'''"
                    if stripped.count("'''") >= 2:
                        in_multiline_string = False
            else:
                # 在多行字符串内部，检查是否结束
                if stripped.endswith(multiline_delimiter):
                    in_multiline_string = False
                # 多行字符串内部行不调整缩进
                processed_lines.append(line)
                i += 1
                continue

            # 不在多行字符串内部，执行缩进修复
            current_indent = len(line) - len(stripped)

            # 检测块开始关键字
            block_keywords = [
                "if ",
                "elif ",
                "else:",
                "for ",
                "while ",
                "def ",
                "class ",
                "try:",
                "except",
                "finally:",
                "with ",
                "async def",
                "async for",
                "async with",
            ]
            is_block_start = False
            if stripped:
                for kw in block_keywords:
                    if stripped.startswith(kw):
                        is_block_start = True
                        break

            if is_block_start and i + 1 < len(lines):
                next_line = lines[i + 1]
                next_stripped = next_line.lstrip()
                next_indent = len(next_line) - len(next_stripped) if next_stripped else 0
                # 如果下一行缩进不足（小于当前行+4），则强制增加
                if next_stripped and next_indent < current_indent + 4:
                    lines[i + 1] = " " * (current_indent + 4) + next_stripped
            processed_lines.append(line)
            i += 1

        # 第三步：重新组合代码，并再次执行 dedent/indent 以统一整体缩进
        fixed_code = "\n".join(processed_lines)
        fixed_code = textwrap.dedent(fixed_code)
        fixed_code = textwrap.indent(fixed_code, "    ")
        return fixed_code


# --- END OF FILE code_normalizer.py ---
