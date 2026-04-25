# src/adami_kernel/nexus/skill_loader.py
import logging

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t

logger = logging.getLogger("AdamI-SkillLoader")


def _nskl_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class SkillLoader:
    """
    AdamI 技能加载同步器（终极精简版）
    已彻底消除 importlib 重复加载，直接读取 Evolution 引擎的真实内存状态，
    完美统一日志与前端的技能计数，消灭幽灵技能与数字不匹配问题。
    【已修复】兼容 boot_manager.py 传入的 components dict
    """

    @staticmethod
    async def load(kernel_or_components):
        """同步 Evolution 引擎的真实加载结果，并统一全局计数
        支持两种调用方式：
        1. 传入完整 kernel 对象（传统方式）
        2. 传入 components dict（boot_manager 拆分后方式）
        """
        # 【兼容层】处理 boot_manager.py 传入的 dict
        if isinstance(kernel_or_components, dict):
            evolution_engine = kernel_or_components.get("evolution_engine")
            skill_market = kernel_or_components.get("skill_market")
            logger.debug(_nskl_t("nskl.debug.components"))
        else:
            # 传统 kernel 对象调用
            evolution_engine = getattr(kernel_or_components, "evolution_engine", None)
            skill_market = getattr(kernel_or_components, "skill_market", None)

        if not evolution_engine:
            logger.error(boot_t("boot.log.skill_loader_no_evolution"))
            return

        # 1. 直接从 Evolution 引擎获取真实的、已通过 AST 审计并在内存中就绪的技能字典
        dynamic_skills = getattr(evolution_engine, "dynamic_skills", {})
        core_instincts = getattr(evolution_engine, "core_instincts", {})

        dynamic_count = len(dynamic_skills)
        instinct_count = len(core_instincts)
        total_real_skills = dynamic_count + instinct_count

        # 2. 打印唯一的、专业且清晰的统计日志
        logger.info(
            boot_t(
                "boot.log.skill_engine_loaded",
                total=total_real_skills,
                instinct=instinct_count,
                dynamic=dynamic_count,
            )
        )

        # 3. 同步给 SkillMarket 保证 WebConsole 计数完全一致
        if skill_market is not None and hasattr(skill_market, "_total_count"):
            skill_market._total_count = total_real_skills
            logger.info(boot_t("boot.log.skill_market_count_locked", total=total_real_skills))
