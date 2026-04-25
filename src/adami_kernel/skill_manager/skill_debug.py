# --- START OF FILE skill_debug.py ---
"""
AdamI Skill Manager - SkillDebug（调试与可观测性工具模块）

提供失败技能代码保存功能，自动写入 .adami_data/failed_skills/ 目录。
文件名包含时间戳、技能名、错误类型，便于后续分析和 observability 追踪。
"""

import logging
import os
from datetime import datetime
from typing import Optional

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.i18n.jinja_render import render_i18n_template

logger = logging.getLogger("AdamI-SkillDebug")


def _skdbg_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class SkillDebug:
    """
    技能调试工具（单一职责）
    仅负责将验证/构建失败的代码保存到本地调试目录。
    """

    @staticmethod
    def save_failed_skill(
        code: str, error_info: str, skill_name: str, error_type: str = "unknown"
    ) -> Optional[str]:
        """
        保存失败的技能代码到调试目录。

        Args:
            code: 失败的原始代码
            error_info: 详细错误信息（行号、上下文、建议等）
            skill_name: 技能名称
            error_type: 错误类型（syntax / security / signature / write 等）

        Returns:
            保存的文件完整路径（成功时）或 None（失败时）
        """
        try:
            # 确保调试目录存在
            debug_dir = settings.path_failed_skills_dir
            os.makedirs(debug_dir, exist_ok=True)

            # 生成带时间戳的文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{timestamp}_{skill_name}_{error_type}.py"
            file_path = os.path.join(debug_dir, filename)

            header = render_i18n_template(
                "skill_debug/failure_header.j2",
                skill_name=skill_name,
                error_type=error_type,
                timestamp=timestamp,
                error_info=error_info or "",
            )
            debug_content = f"{header}\n{code}\n"

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(debug_content)

            logger.info(_skdbg_t("skdbg.log.saved", path=file_path))
            return file_path

        except Exception as e:
            logger.error(_skdbg_t("skdbg.err.save", e=e))
            return None


# --- END OF FILE skill_debug.py ---
