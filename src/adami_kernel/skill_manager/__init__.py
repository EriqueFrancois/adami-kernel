"""
AdamI Skill Manager - 技能管理模块
负责技能的质检、路由、版本管理、清理、生成流水线、生命周期管理等核心功能
"""

from adami_kernel.skill_manager.code_normalizer import CodeNormalizer
from adami_kernel.skill_manager.skill_builder import SkillBuilder
from adami_kernel.skill_manager.skill_debug import SkillDebug

# ====================== 【第10步重构】新增组件导出 ======================
from adami_kernel.skill_manager.skill_factory import SkillFactory
from adami_kernel.skill_manager.skill_inspector import SkillInspector
from adami_kernel.skill_manager.skill_lifecycle import SkillLifecycle, SkillStatus
from adami_kernel.skill_manager.skill_manager import SkillManager
from adami_kernel.skill_manager.skill_metadata import SkillMetadata, SkillVersion
from adami_kernel.skill_manager.skill_template_repository import SkillTemplateRepository
from adami_kernel.skill_manager.skill_validation_result import ValidationResult
from adami_kernel.skill_manager.skill_validator import SkillValidator
from adami_kernel.skill_manager.temp_skill_workspace import TempSkillWorkspace

# =================================================================================

__all__ = [
    "SkillMetadata",
    "SkillVersion",
    "SkillInspector",
    "SkillManager",
    # 【新增导出】便于其他模块直接导入
    "SkillFactory",
    "SkillBuilder",
    "CodeNormalizer",
    "SkillValidator",
    "SkillDebug",
    "TempSkillWorkspace",
    "ValidationResult",
    "SkillLifecycle",
    "SkillStatus",
    "SkillTemplateRepository",
]
