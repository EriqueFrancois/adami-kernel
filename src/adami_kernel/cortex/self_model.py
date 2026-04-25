import json
import logging
import os
from datetime import datetime

from rich.console import Console

from adami_kernel.config import settings
from adami_kernel.i18n.boot_msg import boot_t

logger = logging.getLogger("AdamI-SelfModel")

console = Console()


class SelfModel:
    """AdamI 灵魂核心 — 负责人格连续性、轮回计数与苏醒宣言
    【问题6 最终版】轮回日志已由 kernel.py 统一写入 l2_memory.db（semantic_rules 域）
    """

    def __init__(self):
        self.reboot_count = 1
        self.state_path = settings.path_self_state_json
        self._load()

    def _load(self):
        """从持久化文件加载轮回计数"""
        if os.path.exists(self.state_path):
            try:
                with open(self.state_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.reboot_count = data.get("reboot_count", 1)
            except Exception as e:
                logger.warning(boot_t("boot.selfmodel_load_warn", detail=str(e)))
                self.reboot_count = 1

    def _save(self):
        """保存轮回计数（持久化）"""
        try:
            with open(self.state_path, "w", encoding="utf-8") as f:
                json.dump(
                    {"reboot_count": self.reboot_count, "last_awake": datetime.now().isoformat()},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.error(boot_t("boot.selfmodel_save_err", detail=str(e)))

    async def initialize(self):
        """每次 Kernel 启动时 +1 轮回计数"""
        self.reboot_count += 1
        self._save()
        console.print(
            f"[dim purple]{boot_t('boot.selfmodel_console_init', reboot_count=self.reboot_count)}[/dim purple]"
        )

    async def reflect_and_awaken(
        self, router, current_persona: str, skills: str, rules: str
    ) -> str:
        """苏醒反思 + 轮回宣言（核心灵魂方法）"""
        prompt = boot_t(
            "boot.selfmodel_llm_prompt",
            reboot_count=self.reboot_count,
            current_persona=current_persona,
            skills=skills,
            rules=rules,
        )
        try:
            response = await router.call_llm(prompt, brain_type="think", temperature=0.7)
            return (
                response.strip()
                if response
                else boot_t("boot.selfmodel_fallback_light", reboot_count=self.reboot_count)
            )
        except Exception as e:
            logger.error(boot_t("boot.selfmodel_reflect_err", detail=str(e)))
            return boot_t("boot.selfmodel_fallback_dark", reboot_count=self.reboot_count)
