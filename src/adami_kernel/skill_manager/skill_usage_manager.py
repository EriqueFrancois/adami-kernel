# --- START OF FILE skill_usage_manager.py ---
"""
AdamI Skill Manager - 使用统计与固化管理模块

本模块集中存放技能使用次数统计、持久化、阈值固化逻辑。
职责单一，通过回调与 EvolutionEngine 解耦。
"""

import json
import logging
import os
from datetime import datetime
from typing import Any, Callable, Dict

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t

logger = logging.getLogger("AdamI-SkillUsageManager")


def _skusm_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class SkillUsageManager:
    """
    技能使用统计与自动固化管理器
    职责：
    - 读取/保存 usage.json
    - 更新使用次数和最后使用时间
    - 达到阈值时触发固化回调
    - 创建带统计的 execute 包装器
    """

    def __init__(self, usage_file: str, on_threshold_reached: Callable[[str], None]):
        """
        :param usage_file: 使用统计 JSON 文件路径
        :param on_threshold_reached: 达到阈值时的回调（EvolutionEngine._instinctualize）
        """
        self.usage_file = usage_file
        self.on_threshold_reached = on_threshold_reached
        self.USAGE_THRESHOLD = 3
        logger.info(boot_t("boot.log.skill_usage_init"))

    def _get_usage(self) -> Dict[str, Dict[str, Any]]:
        """读取使用统计"""
        if os.path.exists(self.usage_file):
            try:
                with open(self.usage_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        for k, v in data.items():
                            if isinstance(v, int):
                                data[k] = {"count": v, "last_used": None}
                        return data
            except Exception as e:
                logger.warning(_skusm_t("skusm.warn.read_usage", e=e))
        return {}

    def _save_usage(self, usage: Dict[str, Dict[str, Any]]):
        """保存使用统计"""
        try:
            os.makedirs(os.path.dirname(self.usage_file), exist_ok=True)
            with open(self.usage_file, "w", encoding="utf-8") as f:
                json.dump(usage, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(_skusm_t("skusm.err.save_usage", e=e))

    def update_usage(self, skill_name: str):
        """更新使用次数并检查是否需要固化"""
        usage = self._get_usage()
        key = skill_name.upper()
        if key not in usage:
            usage[key] = {"count": 0, "last_used": None}
        usage[key]["count"] += 1
        usage[key]["last_used"] = datetime.now().isoformat()

        self._save_usage(usage)

        # 达到阈值触发固化
        if usage[key]["count"] >= self.USAGE_THRESHOLD:
            logger.info(_skusm_t("skusm.log.threshold", name=skill_name, th=self.USAGE_THRESHOLD))
            self.on_threshold_reached(skill_name)

    def create_execute_wrapper(self, original_execute, skill_name: str, is_instinct: bool = False):
        """创建带使用统计的 execute 包装器"""

        async def wrapped_execute(*args, **kwargs):
            if not is_instinct:
                self.update_usage(skill_name)
            return await original_execute(*args, **kwargs)

        wrapped_execute.__doc__ = getattr(original_execute, "__doc__", "")
        return wrapped_execute


# --- END OF FILE skill_usage_manager.py ---
