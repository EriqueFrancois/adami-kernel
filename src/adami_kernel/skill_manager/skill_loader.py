# src/adami_kernel/skill_manager/skill_loader.py
# --- START OF FILE skill_loader.py ---
"""
AdamI Skill Manager - SkillLoader（加载职责拆分）

.. note::
    运行时引导使用的是 ``adami_kernel.nexus.skill_loader.SkillLoader``（从 Evolution 内存同步计数）。
    本模块为历史/备用实现；若在其他分支引用，请优先与 ``SkillFileLoader`` 行为对齐。

仅负责从已写入的文件动态导入并注册到内存。
不包含任何格式化、清洗、AST 验证逻辑（这些已在 SkillBuilder 中完成）。
加载时从正式目录读取，加载失败仅记录错误，文件保留（由清理器定期清理）。

【v2.2 核心集成】：Anthropic Skills 官方技能加载全面支持（缓存 + 异步执行模块）
"""

import importlib.util
import logging
import os
from typing import Any, Callable

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t

# ====================== 【步骤5 新增】Anthropic Skills 支持 ======================
from adami_kernel.skill_manager.anthropic_skill_importer import AnthropicSkillImporter

# ==================================================================================

logger = logging.getLogger("AdamI-SkillLoader")


def _skldr_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class SkillLoader:
    """
    SkillLoader（单一职责）
    仅负责动态导入已写入的技能文件并注册到内存。
    【v2.2 新增】支持 Anthropic Skills 官方技能加载（缓存 + 异步执行）
    """

    def __init__(
        self,
        skills_dir: str,
        instincts_dir: str,
        on_skill_loaded: Callable[[str, Any], None],
    ):
        """
        :param skills_dir: 动态技能目录（由 SkillBuilder 写入）
        :param instincts_dir: 固化本能目录
        :param on_skill_loaded: 加载成功后的回调（skill_name, module）
        """
        self.skills_dir = skills_dir
        self.instincts_dir = instincts_dir
        self.on_skill_loaded = on_skill_loaded

        # ====================== 【步骤5 新增】Anthropic Importer + 缓存 ======================
        self.anthropic_importer = AnthropicSkillImporter()
        self.anthropic_skills_cache: list = []  # 缓存已加载的 Anthropic 技能
        # ==================================================================================

        os.makedirs(self.skills_dir, exist_ok=True)
        os.makedirs(self.instincts_dir, exist_ok=True)
        logger.info(boot_t("boot.log.skill_manager_loader_init"))

    async def load_from_directory(self, directory: str, is_instinct: bool = False):
        """从目录加载所有 .py 文件并动态导入"""
        if not os.path.exists(directory):
            return

        for file in os.listdir(directory):
            if file.endswith(".py") and not file.startswith("__"):
                skill_name = file[:-3].upper()
                file_path = os.path.join(directory, file)

                try:
                    spec = importlib.util.spec_from_file_location(skill_name, file_path)
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)

                        if hasattr(module, "execute"):
                            self.on_skill_loaded(skill_name, module)
                            logger.info(
                                boot_t(
                                    "boot.log.skill_manager_loaded_instinct"
                                    if is_instinct
                                    else "boot.log.skill_manager_loaded_dynamic",
                                    name=skill_name,
                                )
                            )
                        else:
                            logger.warning(_skldr_t("skldr.warn.no_execute", file=file))
                except Exception as e:
                    logger.error(_skldr_t("skldr.err.load", name=skill_name, e=e))

    # ====================== 【步骤5 增强】Anthropic Skills 加载 ======================
    async def load_anthropic_skills(self):
        """加载 Anthropic 官方技能（转换为 Adami 可执行异步模块）"""
        if self.anthropic_skills_cache:
            logger.info(_skldr_t("skldr.log.anthropic_cache", n=len(self.anthropic_skills_cache)))
            for skill_meta in self.anthropic_skills_cache:
                self.on_skill_loaded(skill_meta.skill_name.upper(), skill_meta.module)
            return

        logger.info(_skldr_t("skldr.log.anthropic_scan"))
        anthropic_metas = self.anthropic_importer.scan_and_import()

        for meta in anthropic_metas:
            try:
                # 转换为真正的异步可执行模块（与动态技能完全一致）
                class AnthropicSkillModule:
                    def __init__(self, meta):
                        self.meta = meta

                    async def execute(self, **kwargs):
                        # Anthropic 技能核心执行逻辑：直接返回 prompt_template（后续可扩展为 LLM 调用）
                        logger.debug(
                            _skldr_t(
                                "skldr.debug.anthropic_exec",
                                nm=self.meta.skill_name,
                                kw=repr(kwargs),
                            )
                        )
                        return {
                            "status": "success",
                            "skill_name": self.meta.skill_name,
                            "result": self.meta.prompt_template,
                            "source": "anthropic-official",
                            **kwargs,  # 透传所有参数
                        }

                module = AnthropicSkillModule(meta)
                # 缓存模块对象
                meta.module = module
                self.anthropic_skills_cache.append(meta)

                self.on_skill_loaded(meta.skill_name.upper(), module)
                logger.info(_skldr_t("skldr.log.anthropic_ok", nm=meta.skill_name))
            except Exception as e:
                logger.error(_skldr_t("skldr.err.anthropic", nm=meta.skill_name, e=e))

    # ==================================================================================

    async def load_genetic_skills(self):
        """统一加载固化本能、动态技能 + Anthropic 官方技能"""
        await self.load_from_directory(self.instincts_dir, is_instinct=True)
        await self.load_from_directory(self.skills_dir, is_instinct=False)
        await self.load_anthropic_skills()  # Anthropic 官方技能最后加载（优先级最高）

    def cleanup_corrupted_skills(self):
        """
        历史 API：曾遍历 skills + instincts 并删除全部 .py，极易误删本能库。
        默认引导路径请使用 ``SkillFileLoader.cleanup_corrupted_skills``（EvolutionEngine）。
        此处仅扫描 **动态 skills_dir**，**从不** 删除 ``instincts_dir``。
        """
        for d in [self.skills_dir]:
            if not os.path.exists(d):
                continue
            for f in list(os.listdir(d)):
                if f.endswith(".py"):
                    try:
                        os.remove(os.path.join(d, f))
                        logger.info(_skldr_t("skldr.log.cleanup_removed", f=f))
                    except Exception as e:
                        logger.warning(_skldr_t("skldr.warn.cleanup", e=e))


# --- END OF FILE skill_loader.py ---
# 文件路径：src/adami_kernel/skill_manager/skill_loader.py
# 版本：v2.2（Anthropic Skills 官方技能加载完整支持版）
