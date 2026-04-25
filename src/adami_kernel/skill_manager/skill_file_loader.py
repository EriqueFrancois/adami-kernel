# src/adami_kernel/skill_manager/skill_file_loader.py
"""
AdamI Skill Manager - 技能文件加载与目录管理模块

本模块集中存放目录挂载、动态导入、残留文件清理逻辑。
通过回调 on_skill_loaded 与 EvolutionEngine 解耦。
【本次重构】：移除对已完整技能文件的二次包装和格式化，直接加载。
【本次修复】：cleanup_corrupted_skills 仅删除明显无效的技能文件，避免误删正常技能。
【本次修改】：新增 SkillManager.is_instinct 保护，跳过本能技能的重复加载。
"""

from __future__ import annotations  # 关键：解决循环导入

import ast
import importlib.util
import logging
import os
import re

# 使用 TYPE_CHECKING 延迟导入，避免循环
from typing import TYPE_CHECKING, Any, Callable, Optional

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t

if TYPE_CHECKING:
    from adami_kernel.skill_manager.skill_manager import SkillManager

logger = logging.getLogger("AdamI-SkillFileLoader")


def _skfl_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


# 技能名称合法性正则（全大写字母、数字、下划线，且以字母开头）
SKILL_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")


class SkillFileLoader:
    """
    技能文件加载器
    职责：
    - 从 skills / instincts 目录加载 .py 文件并动态导入
    - 清理残留的无效技能文件
    - 支持回调注入（加载完成后通知 EvolutionEngine 完成注册）
    【本次修改】：新增本能固化保护，跳过已固化技能的重复加载/构建
    """

    def __init__(
        self,
        skills_dir: str,
        instincts_dir: str,
        on_skill_loaded: Callable[[str, Any, bool], None],
        skill_manager: Optional["SkillManager"] = None,  # 使用字符串类型提示
    ):
        """
        :param skills_dir: 动态技能目录
        :param instincts_dir: 固化本能目录
        :param on_skill_loaded: 加载成功后的回调（skill_name, module, is_instinct）
        :param skill_manager: SkillManager 实例（用于 is_instinct 判断）
        """
        self.skills_dir = skills_dir
        self.instincts_dir = instincts_dir
        self.on_skill_loaded = on_skill_loaded
        self.skill_manager = skill_manager  # 本能保护依赖
        os.makedirs(self.skills_dir, exist_ok=True)
        os.makedirs(self.instincts_dir, exist_ok=True)
        logger.info(boot_t("boot.log.skill_file_loader_init"))

    async def load_from_directory(self, directory: str, is_instinct: bool):
        """从指定目录加载所有 .py 文件并动态导入（直接使用文件内容，不重新包装）"""
        if not os.path.exists(directory):
            return

        for file in os.listdir(directory):
            if file.endswith(".py") and not file.startswith("__"):
                skill_name = file[:-3].upper()
                file_path = os.path.join(directory, file)

                # 动态目录：若本能目录已有同名技能文件，以本能为准（文件名可能为大写或小写）
                if not is_instinct:
                    _ins_l = os.path.join(self.instincts_dir, f"{skill_name.lower()}.py")
                    _ins_u = os.path.join(self.instincts_dir, f"{skill_name.upper()}.py")
                    if os.path.isfile(_ins_l) or os.path.isfile(_ins_u):
                        logger.info(_skfl_t("skfl.log.skip_dup_instinct_file", name=skill_name))
                        continue

                # ====================== 【步骤4 新增】本能固化保护 ======================
                if self.skill_manager and self.skill_manager.is_instinct(skill_name):
                    logger.info(_skfl_t("skfl.log.skip_instinct", name=skill_name))
                    continue
                # =====================================================================

                try:
                    with open(file_path, "r", encoding="utf-8") as f:
                        code = f.read()

                    # 语法验证（仅验证，不修改代码）
                    try:
                        ast.parse(code)
                    except SyntaxError as e:
                        logger.error(_skfl_t("skfl.err.syntax", name=skill_name, e=e))
                        continue

                    # 动态导入
                    spec = importlib.util.spec_from_file_location(skill_name, file_path)
                    if spec and spec.loader:
                        module = importlib.util.module_from_spec(spec)
                        spec.loader.exec_module(module)
                        if hasattr(module, "execute"):
                            self.on_skill_loaded(skill_name, module, is_instinct)
                            logger.info(
                                boot_t(
                                    "boot.log.skill_file_loader_loaded_instinct"
                                    if is_instinct
                                    else "boot.log.skill_file_loader_loaded_dynamic",
                                    name=skill_name,
                                )
                            )
                        else:
                            logger.warning(_skfl_t("skfl.warn.no_execute", file=file))
                except Exception as e:
                    logger.error(_skfl_t("skfl.err.load", name=skill_name, e=e))

    async def load_genetic_skills(self):
        """加载固化本能和动态技能（统一入口）"""
        await self.load_from_directory(self.instincts_dir, is_instinct=True)
        await self.load_from_directory(self.skills_dir, is_instinct=False)

    def cleanup_corrupted_skills(self):
        """
        清理残留的无效技能文件（启动时调用）
        只删除明显无效的文件，避免误删正常技能。
        """
        for d in [self.skills_dir, self.instincts_dir]:
            if not os.path.exists(d):
                continue
            for f in list(os.listdir(d)):
                if not f.endswith(".py"):
                    continue
                file_path = os.path.join(d, f)
                skill_name = f[:-3].upper()

                # 1. 检查文件名是否合法
                if not SKILL_NAME_PATTERN.match(skill_name):
                    logger.info(_skfl_t("skfl.log.del_bad_name", f=f))
                    try:
                        os.remove(file_path)
                    except Exception as e:
                        logger.warning(_skfl_t("skfl.warn.del_fail", f=f, e=e))
                    continue

                # 2. 检查文件内容是否包含 execute 函数
                try:
                    with open(file_path, "r", encoding="utf-8") as file:
                        content = file.read()
                    if len(content.strip()) < 50:
                        logger.info(_skfl_t("skfl.log.del_short", f=f))
                        os.remove(file_path)
                        continue
                    if "async def execute" not in content:
                        logger.info(_skfl_t("skfl.log.del_no_execute", f=f))
                        os.remove(file_path)
                        continue
                except Exception as e:
                    logger.warning(_skfl_t("skfl.warn.read_skip", f=f, e=e))
                    continue
