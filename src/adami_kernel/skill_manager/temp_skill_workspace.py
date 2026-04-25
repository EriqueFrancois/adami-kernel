# --- START OF FILE temp_skill_workspace.py ---
"""
AdamI Skill Manager - TempSkillWorkspace（解耦技能文件与内存对象）

提供临时工作区机制：先在临时目录生成/验证文件，通过后再移动到正式目录。
彻底避免无效文件落地正式目录，实现文件操作与内存加载的完全解耦。
"""

import logging
import os
import shutil
from datetime import datetime
from typing import Optional

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t

logger = logging.getLogger("AdamI-TempSkillWorkspace")


def _tmpws_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class TempSkillWorkspace:
    """
    临时技能工作区（单一职责）
    所有技能文件先在临时目录操作，通过验证后才移动到正式目录。
    """

    def __init__(self):
        self.temp_dir = settings.path_temp_skills_dir
        self.final_skills_dir = settings.path_final_skills_dir
        os.makedirs(self.temp_dir, exist_ok=True)
        os.makedirs(self.final_skills_dir, exist_ok=True)
        logger.info(boot_t("boot.log.temp_workspace_init"))

    def create_temp_file(self, skill_name: str, code: str) -> str:
        """
        在临时目录创建临时文件，返回临时文件路径。
        """
        # 生成带时间戳的安全文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        temp_filename = f"{timestamp}_{skill_name}.py"
        temp_path = os.path.join(self.temp_dir, temp_filename)

        try:
            with open(temp_path, "w", encoding="utf-8") as f:
                f.write(code)
            logger.debug(_tmpws_t("tmpws.debug.temp_created", path=temp_path))
            return temp_path
        except Exception as e:
            logger.error(_tmpws_t("tmpws.err.create", e=e))
            raise

    async def validate_and_commit(self, temp_path: str, final_name: str) -> Optional[str]:
        """
        验证临时文件通过后，移动到正式目录。
        返回最终文件路径（成功时）或 None（失败时）。
        """
        final_path = os.path.join(self.final_skills_dir, f"{final_name}.py")

        try:
            # 移动到正式目录（原子操作）
            shutil.move(temp_path, final_path)
            logger.info(_tmpws_t("tmpws.log.committed", path=final_path))
            return final_path
        except Exception as e:
            logger.error(_tmpws_t("tmpws.err.commit", e=e))
            # 清理临时文件
            try:
                os.unlink(temp_path)
            except Exception:
                pass
            return None

    def cleanup(self) -> int:
        """
        清理临时目录中的所有文件（启动时或失败后调用）。
        返回清理的文件数量。
        """
        if not os.path.exists(self.temp_dir):
            return 0

        cleaned_count = 0
        for f in os.listdir(self.temp_dir):
            try:
                os.unlink(os.path.join(self.temp_dir, f))
                cleaned_count += 1
            except Exception as e:
                logger.warning(_tmpws_t("tmpws.warn.clean_file", f=f, e=e))

        logger.info(_tmpws_t("tmpws.log.clean_done", n=cleaned_count))
        return cleaned_count


# --- END OF FILE temp_skill_workspace.py ---
