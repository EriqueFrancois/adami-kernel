# src/adami_kernel/skill_manager/skill_manager.py
# --- START OF FILE skill_manager.py ---

import asyncio
import logging
import os

# ==================================================================================
# 避免循环导入，使用 TYPE_CHECKING
from typing import TYPE_CHECKING, Any, Dict, Optional, Set

from adami_kernel.config import settings
from adami_kernel.cortex.dream_sandbox import DreamSandbox
from adami_kernel.cortex.evolution import EvolutionEngine
from adami_kernel.cortex.router import LLMRouter
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.i18n import t

# ====================== 【步骤6 新增】Anthropic Skills 支持 ======================
from adami_kernel.skill_manager.anthropic_skill_importer import AnthropicSkillImporter
from adami_kernel.skill_manager.skill_inspector import SkillInspector
from adami_kernel.skill_manager.skill_lifecycle import SkillLifecycle, SkillStatus
from adami_kernel.skill_manager.skill_metadata import (
    SkillMetadata,
    SkillVersion,
    serialize_skill_metadata,
)
from adami_kernel.skill_manager.skill_version_manager import SkillVersionManager

if TYPE_CHECKING:
    from adami_kernel.skill_manager.skill_optimizer import SkillOptimizer
    from adami_kernel.skill_manager.vector_store import VectorStore

logger = logging.getLogger("AdamI-SkillManager")


def _sm_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class SkillManager:
    """
    技能管理器 (Skill Manager) - Phase 3 + 向量实时同步增强版 + 第二阶段 protected 支持
    职责：
    - 提供统一的技能注册入口（inspect_and_register）
    - 协调质检、元数据存储、底层 EvolutionEngine 注册
    - 集成版本管理器（SkillVersionManager），记录执行结果并更新评分
    - 实时同步技能元数据到 VectorStore，消除路由盲区
    - 【本次新增】protected 标记支持（CodeQualityScorer 保守决策使用）
    【步骤6 集成】：完整支持 Anthropic Skills 官方技能注册、元数据同步和生命周期管理
    【v2.4 最终版】：增加 Anthropic 缓存 + 健壮性保护（解决 import_single_skill AttributeError）+ 自动 protected 标记
    【本次审计】：与 SkillRouter / SkillComposer / SkillLoader 全局对齐
    【本次修复】：get_skill_metadata 完全同步调用，避免 await NoneType 错误
    """

    def __init__(
        self,
        memory: LayeredMemory,
        evolution_engine: EvolutionEngine,
        dream_sandbox: DreamSandbox,
        router: LLMRouter,
        vector_store: Optional["VectorStore"] = None,
        skill_optimizer: Optional["SkillOptimizer"] = None,
    ):
        self.memory = memory
        self.evolution = evolution_engine
        self.inspector = SkillInspector(dream_sandbox, router)
        self.version_manager = SkillVersionManager(memory, evolution_engine)
        self.vector_store = vector_store
        self.skill_optimizer = skill_optimizer

        # ====================== 【步骤6 新增】Anthropic Skill Importer + 缓存 ======================
        self.anthropic_importer = AnthropicSkillImporter()
        self._anthropic_cache: Dict[str, Any] = {}  # 缓存 Anthropic 元数据
        # ==================================================================================

        # ====================== 【第一阶段】本能固化集合 ======================
        self.instinct_skills: Set[str] = set()
        # =====================================================================

        # ====================== 【第二阶段】protected 标记支持 ======================
        # protected_skills 集合由 SkillVersionManager 持久化管理，此处仅做缓存加速
        # =====================================================================

        # 生命周期状态机字典
        self._lifecycle: Dict[str, SkillLifecycle] = {}

        # 如果创建时 optimizer 已存在，则立即注入
        if skill_optimizer:
            self.version_manager.set_skill_optimizer(skill_optimizer)

        logger.info("[SkillManager] ready")
        if vector_store:
            logger.debug("[SkillManager] vector_store attached")
        else:
            logger.warning(_sm_t("skmg.warn.no_vector"))

        logger.debug("[SkillManager] dynamic scoring paused; VersionManager handles versions")

    def is_instinct(self, skill_name: str) -> bool:
        skill_name = skill_name.upper()
        if skill_name in self.instinct_skills:
            return True
        return self.version_manager.is_instinct(skill_name)

    def refresh_instinct_cache_from_disk(self) -> None:
        """启动后根据 ``instincts/`` 目录同步内存中的本能集合，避免重启后 instinct_skills 为空。"""
        base = getattr(self.evolution, "instincts_dir", None)
        if not base or not os.path.isdir(base):
            return
        for fn in os.listdir(base):
            if not fn.endswith(".py") or fn.startswith("__"):
                continue
            self.instinct_skills.add(fn[:-3].upper())

    def is_protected(self, skill_name: str) -> bool:
        skill_name = skill_name.upper()
        return self.version_manager.is_protected(skill_name)

    def set_skill_optimizer(self, skill_optimizer: "SkillOptimizer") -> None:
        self.skill_optimizer = skill_optimizer
        if self.version_manager:
            self.version_manager.set_skill_optimizer(skill_optimizer)
        logger.debug("[SkillManager] SkillOptimizer set")

    async def inspect_and_register(
        self,
        skill_name: str,
        code: str,
        description: str,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        skill_name = skill_name.upper()

        # ====================== 【Anthropic Skills 特殊处理 v2.4】 ======================
        if skill_name.startswith("ANTHROPIC_") or "anthropic" in description.lower():
            if skill_name not in self._anthropic_cache:
                try:
                    anthropic_meta = self.anthropic_importer.import_single_skill(skill_name.lower())
                    if anthropic_meta:
                        self._anthropic_cache[skill_name] = anthropic_meta
                        code = anthropic_meta.prompt_template
                        logger.info(_sm_t("skmg.log.anthropic_tpl", skill_name=skill_name))
                except AttributeError:
                    logger.debug(_sm_t("skmg.log.anthropic_attr"))
                except Exception as e:
                    logger.warning(_sm_t("skmg.log.anthropic_fail", err=e))
            else:
                code = self._anthropic_cache[skill_name].prompt_template
        # =====================================================================

        # 已存在且 ACTIVE 时直接返回
        existing = await self.get_skill_metadata(skill_name)
        if existing and getattr(existing, "status", None) == "active":
            logger.info(_sm_t("skmg.log.exists_active", skill_name=skill_name))
            return {"status": "success", "skill_name": skill_name, "already_exists": True}

        if skill_name in self._lifecycle:
            old_status = self._lifecycle[skill_name].current_status
            if old_status != SkillStatus.DEPRECATED:
                logger.debug(
                    _sm_t(
                        "skmg.log.lifecycle_recreate",
                        skill_name=skill_name,
                        old_status=old_status.name,
                    )
                )
                del self._lifecycle[skill_name]

        self._lifecycle[skill_name] = SkillLifecycle(skill_name=skill_name)
        self._lifecycle[skill_name].transition_to(
            SkillStatus.CREATED, _sm_t("skmg.lifecycle.code_gen_done")
        )

        inspection = await self.inspector.inspect_and_register(
            skill_name=skill_name, code=code, description=description, max_retries=max_retries
        )
        if not inspection.get("passed", False):
            logger.warning(
                _sm_t(
                    "skmg.log.inspect_fail",
                    skill_name=skill_name,
                    feedback=inspection.get("feedback"),
                )
            )
            return {
                "status": "error",
                "skill_name": skill_name,
                "feedback": inspection.get("feedback", _sm_t("skill.mgr.inspect_failed_default")),
            }

        self._lifecycle[skill_name].transition_to(
            SkillStatus.VALIDATED, _sm_t("skmg.lifecycle.inspection_ok")
        )

        try:
            result = await self.evolution.create_new_skill(
                skill_name=skill_name, description=description, code=code, skip_inspection=True
            )
        except Exception as e:
            logger.error(_sm_t("skmg.log.reg_evolution_fail", skill_name=skill_name, err=e))
            return {
                "status": "error",
                "skill_name": skill_name,
                "feedback": _sm_t("skill.mgr.register_system_failed", detail=str(e)),
            }

        if result.get("status") != "success":
            return {
                "status": "error",
                "skill_name": skill_name,
                "feedback": result.get("error", _sm_t("skill.mgr.register_failed_default")),
            }

        self._lifecycle[skill_name].transition_to(
            SkillStatus.LOADED, _sm_t("skmg.lifecycle.loaded")
        )

        if skill_name.startswith("ANTHROPIC_"):
            logger.info(_sm_t("skmg.log.anthropic_protected", skill_name=skill_name))

        if self.is_instinct(skill_name):
            self.instinct_skills.add(skill_name)
            logger.info(_sm_t("skmg.log.instinct_add", skill_name=skill_name))

        metadata_obj = SkillMetadata(
            skill_name=skill_name,
            current_version="v1.0",
            score=100.0,
            versions={
                "v1.0": SkillVersion(
                    version="v1.0", code=code, score=100.0, reason="Anthropic official skill"
                )
            },
        )
        payload = serialize_skill_metadata(metadata_obj)
        await self.memory.store_experience(
            trace_id=f"skill_register_{skill_name}_{metadata_obj.current_version}",
            domain="skill_metadata",
            payload=payload,
            chat_id="system",
        )
        logger.info(_sm_t("skmg.log.register_ok", skill_name=skill_name))

        if self.vector_store and metadata_obj:
            try:
                meta_dict = serialize_skill_metadata(metadata_obj)
                for attempt in range(3):
                    try:
                        await self.vector_store.add_skill(
                            skill_name=skill_name, description=description, metadata=meta_dict
                        )
                        break
                    except Exception as sync_e:
                        logger.warning(
                            _sm_t(
                                "skmg.log.vs_sync_retry",
                                attempt=attempt + 1,
                                err=sync_e,
                            )
                        )
                        await asyncio.sleep(0.5)
            except Exception as e:
                logger.warning(_sm_t("skmg.log.vs_sync_fail", skill_name=skill_name, err=e))

        self._lifecycle[skill_name].transition_to(
            SkillStatus.ACTIVE, _sm_t("skmg.lifecycle.active")
        )

        return {"status": "success", "skill_name": skill_name, "data": result.get("data", {})}

    async def record_execution_result(
        self, skill_name: str, success: bool, details: Optional[Dict] = None
    ) -> None:
        logger.info(_sm_t("skmg.log.scoring_paused", skill_name=skill_name, success=success))
        await self.version_manager.record_execution_result(skill_name, success, details)

        if self.is_protected(skill_name):
            logger.info(_sm_t("skmg.log.protected", skill_name=skill_name))
        if self.is_instinct(skill_name):
            self.instinct_skills.add(skill_name)
            logger.info(_sm_t("skmg.log.instinct_auto", skill_name=skill_name))

        if skill_name in self._lifecycle and not success:
            if details and details.get("failure_count", 0) >= 3:
                self._lifecycle[skill_name].transition_to(
                    SkillStatus.DEPRECATED, _sm_t("skmg.lifecycle.deprecated_failures")
                )
                logger.info(_sm_t("skmg.log.deprecated", skill_name=skill_name))

    async def get_skill_metadata(self, skill_name: str) -> Optional[SkillMetadata]:
        """与 ``inspect_and_register`` 一致：Anthropic 相关缓存键统一为 ``skill_name.upper()``。"""
        skill_key = skill_name.upper()
        skill_name_lower = skill_name.lower()

        if skill_key in self._anthropic_cache:
            return self._anthropic_cache[skill_key]

        try:
            anthropic_meta = self.anthropic_importer.import_single_skill(skill_name_lower)
            if anthropic_meta:
                self._anthropic_cache[skill_key] = anthropic_meta
                return anthropic_meta
        except AttributeError:
            logger.debug(_sm_t("skmg.log.anthropic_mem"))
        except Exception as e:
            logger.warning(_sm_t("skmg.log.anthropic_fail", err=e))

        domain = "skill_metadata"
        records = await self.memory.retrieve_recent(domain=domain, limit=10, chat_id="system")
        for record in records:
            if record.get("skill_name", "").upper() == skill_name.upper():
                try:
                    return SkillMetadata.model_validate(record)
                except Exception as e:
                    logger.error(_sm_t("skmg.log.parse_meta_fail", err=e))
        return None

    async def get_skill_status(self, skill_name: str) -> tuple[str, float, int]:
        if skill_name in self._lifecycle:
            status = self._lifecycle[skill_name].get_status().name
            version_status = await self.version_manager.get_skill_status(skill_name)
            return (status, version_status[1], version_status[2])
        return await self.version_manager.get_skill_status(skill_name)

    async def trigger_cleanup(self):
        logger.info(_sm_t("skmg.log.cleanup_req"))
        return {"cleaned": 0, "reason": _sm_t("skmg.cleanup.reason")}


# --- END OF FILE skill_manager.py ---
# 文件路径：src/adami_kernel/skill_manager/skill_manager.py
# 版本：v2.4（Anthropic Skills 官方技能完整注册 + 缓存 + 最终健壮版）
