# src/adami_kernel/skill_manager/skill_version_manager.py
# --- START OF FILE skill_version_manager.py ---

import asyncio
import logging
import os
import re
from datetime import datetime

# 避免循环导入，使用 TYPE_CHECKING
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

from adami_kernel.config import settings
from adami_kernel.cortex.evolution import EvolutionEngine
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.i18n import t
from adami_kernel.skill_manager.skill_metadata import SkillMetadata, SkillVersion

if TYPE_CHECKING:
    from adami_kernel.skill_manager.skill_optimizer import SkillOptimizer

logger = logging.getLogger("AdamI-SkillVersionManager")


def _skver_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


# 技能名称合法性正则（全大写字母、数字、下划线，且以字母开头）
SKILL_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")

# ====================== 【本能固化阈值】 ======================
INSTINCT_MIN_USES = 30  # 至少使用 30 次
INSTINCT_MIN_SCORE = 90  # 平均评分 ≥ 90
INSTINCT_MAX_CONSECUTIVE_FAILURES = 0  # 连续失败次数必须为 0

# ====================== 【第四阶段新增】TDD 本能固化最终阈值 ======================
INSTINCT_TDD_MIN_TOTAL_CALLS = 50  # 总使用次数 >= 50
INSTINCT_TDD_MIN_SCORE = 92  # 平均评分 >= 92
INSTINCT_TDD_MIN_CONSECUTIVE_PASSES = 3  # 连续 3 个版本 TDD 全通过
# ==============================================================================


class SkillVersionManager:
    """
    技能版本与动态评分管理器（Phase 3 + 第二阶段 + 第四阶段 TDD 闭环）
    职责：
    - 内存缓存所有技能元数据，避免频繁数据库读写。
    - 定期全量刷盘，使用 clear_and_rewrite_domain 覆盖旧记录，防止元数据膨胀。
    - 提供待优化技能列表，供外部自动优化器调用。
    - 支持动态注入 SkillOptimizer，实现即时优化。
    【本次新增】：TDD 通过计数 + 本能固化最终逻辑（TDD 连续通过 3 次 + 高分 + 高使用量）
    【保留】：完整 protected、本能固化、缓存刷盘机制
    """

    def __init__(self, memory: LayeredMemory, evolution_engine: EvolutionEngine):
        self.memory = memory
        self.evolution_engine = evolution_engine

        # 评分策略参数
        self.SUCCESS_INCREMENT = 5
        self.FAILURE_PENALTY = 20
        self.CONSECUTIVE_FAILURE_THRESHOLD = 3
        self.SCORE_THRESHOLD_OPTIMIZATION = 60
        self.SCORE_THRESHOLD_DEPRECATED = 30

        # ====================== 【本能固化参数】 ======================
        self.INSTINCT_MIN_USES = INSTINCT_MIN_USES
        self.INSTINCT_MIN_SCORE = INSTINCT_MIN_SCORE
        self.INSTINCT_MAX_CONSECUTIVE_FAILURES = INSTINCT_MAX_CONSECUTIVE_FAILURES
        # ============================================================

        # ====================== 【第四阶段新增】TDD 本能固化参数 ======================
        self.INSTINCT_TDD_MIN_TOTAL_CALLS = INSTINCT_TDD_MIN_TOTAL_CALLS
        self.INSTINCT_TDD_MIN_SCORE = INSTINCT_TDD_MIN_SCORE
        self.INSTINCT_TDD_MIN_CONSECUTIVE_PASSES = INSTINCT_TDD_MIN_CONSECUTIVE_PASSES
        # ==============================================================================

        # 内存缓存与锁
        self._metadata_cache: Dict[str, SkillMetadata] = {}
        self._cache_lock = asyncio.Lock()

        # 后台刷盘任务
        self._flush_interval = 300  # 秒
        self._flush_task: Optional[asyncio.Task] = None
        self._running = False
        self._boot_initialized = False

        # 技能优化器（可选，后注入）
        self.skill_optimizer: Optional["SkillOptimizer"] = None

        logger.debug(
            _skver_t(
                "skver.debug.init",
                iu=self.INSTINCT_MIN_USES,
                isc=self.INSTINCT_MIN_SCORE,
                tu=self.INSTINCT_TDD_MIN_TOTAL_CALLS,
                ts=self.INSTINCT_TDD_MIN_SCORE,
                tp=self.INSTINCT_TDD_MIN_CONSECUTIVE_PASSES,
            )
        )

    def set_skill_optimizer(self, skill_optimizer: "SkillOptimizer") -> None:
        """动态注入 SkillOptimizer 实例"""
        self.skill_optimizer = skill_optimizer
        logger.debug(_skver_t("skver.debug.optimizer_set"))

    async def initialize(self):
        """加载现有元数据并启动后台刷盘任务（幂等，可多次调用）"""
        if self._boot_initialized:
            return
        self._boot_initialized = True
        await self._load_all_metadata()
        self._running = True
        self._flush_task = asyncio.create_task(self._flush_loop())
        logger.debug(_skver_t("skver.debug.cache_started"))

    async def get_skill_metadata(self, skill_name: str) -> Optional[SkillMetadata]:
        """读取单条技能元数据（缓存优先，未命中则查 LayeredMemory）。供 SkillCleaner 等模块与 SkillManager 对齐。"""
        skill_name = skill_name.upper()
        if not SKILL_NAME_PATTERN.match(skill_name):
            logger.debug(_skver_t("skver.debug.bad_name_get", name=skill_name))
            return None
        async with self._cache_lock:
            cached = self._metadata_cache.get(skill_name)
            if cached is not None:
                return cached
        return await self._get_skill_metadata_from_db(skill_name)

    async def _load_all_metadata(self):
        """从数据库加载所有技能元数据到缓存（过滤非法技能名）"""
        all_records = await self.memory.retrieve_recent(
            domain="skill_metadata", limit=1000, chat_id="system"
        )
        async with self._cache_lock:
            self._metadata_cache.clear()
            for record in all_records:
                skill_name = record.get("skill_name")
                if not skill_name:
                    continue
                if not SKILL_NAME_PATTERN.match(skill_name):
                    logger.debug(_skver_t("skver.debug.bad_name_load", name=skill_name))
                    continue
                try:
                    metadata = SkillMetadata.model_validate(record)
                    self._metadata_cache[skill_name] = metadata
                except Exception as e:
                    logger.warning(_skver_t("skver.warn.parse_meta", e=e))

    async def _flush_all(self):
        """将缓存中所有元数据全量写入数据库（覆盖旧记录）"""
        async with self._cache_lock:
            if not self._metadata_cache:
                return
            new_payloads = []
            for metadata in self._metadata_cache.values():
                payload = metadata.model_dump()
                if "created_at" in payload and hasattr(payload["created_at"], "isoformat"):
                    payload["created_at"] = payload["created_at"].isoformat()
                if "updated_at" in payload and hasattr(payload["updated_at"], "isoformat"):
                    payload["updated_at"] = payload["updated_at"].isoformat()
                if "versions" in payload:
                    for ver in payload["versions"].values():
                        if "created_at" in ver and hasattr(ver["created_at"], "isoformat"):
                            ver["created_at"] = ver["created_at"].isoformat()
                new_payloads.append(payload)

        if not new_payloads:
            return

        try:
            await self.memory.clear_and_rewrite_domain(
                domain="skill_metadata", new_payloads=new_payloads, chat_id="system"
            )
            logger.debug(_skver_t("skver.debug.flushed_n", n=len(new_payloads)))
        except Exception as e:
            logger.error(_skver_t("skver.err.flush", e=e))

    async def _flush_loop(self):
        """后台定期刷盘"""
        while self._running:
            try:
                await asyncio.sleep(self._flush_interval)
                await self._flush_all()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(_skver_t("skver.err.flush_loop", e=e))
                await asyncio.sleep(10)

    async def shutdown(self):
        """优雅关闭，停止后台任务并最后一次刷盘"""
        self._running = False
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self._flush_all()
        logger.info(_skver_t("skver.log.shutdown_flush"))

    # ====================== 【第四阶段新增】TDD 结果记录 ======================
    async def record_tdd_result(self, skill_name: str, tdd_passed: bool) -> None:
        """记录 TDD 测试结果，更新 TDD 计数（供 SkillOptimizer 调用）"""
        skill_name = skill_name.upper()
        async with self._cache_lock:
            metadata = self._metadata_cache.get(skill_name)
            if not metadata:
                metadata = await self._get_skill_metadata_from_db(skill_name)
                if not metadata:
                    metadata = SkillMetadata(
                        skill_name=skill_name,
                        current_version="v1.0",
                        versions={
                            "v1.0": SkillVersion(
                                version="v1.0",
                                code="",
                                score=100.0,
                                reason="auto-created for TDD metrics",
                            )
                        },
                    )
                self._metadata_cache[skill_name] = metadata

            metrics = metadata.metrics
            metrics["tdd_total_runs"] = metrics.get("tdd_total_runs", 0) + 1
            if tdd_passed:
                metrics["tdd_passes"] = metrics.get("tdd_passes", 0) + 1
                metrics["tdd_consecutive_passes"] = metrics.get("tdd_consecutive_passes", 0) + 1
            else:
                metrics["tdd_consecutive_passes"] = 0

            metadata.updated_at = datetime.now()
            await self._flush_to_memory(skill_name, metadata)

            logger.info(
                _skver_t(
                    "skver.log.tdd_record",
                    name=skill_name,
                    p=tdd_passed,
                    c=metrics.get("tdd_consecutive_passes", 0),
                )
            )

    # =====================================================================

    async def record_execution_result(
        self, skill_name: str, success: bool, details: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        记录技能执行结果，更新内存中的元数据（延迟刷盘）。
        【保留】：记录使用次数，用于本能固化判断
        """
        skill_name = skill_name.upper()

        async with self._cache_lock:
            metadata = self._metadata_cache.get(skill_name)
            if not metadata:
                metadata = await self._get_skill_metadata_from_db(skill_name)
                if metadata:
                    self._metadata_cache[skill_name] = metadata
                else:
                    logger.warning(_skver_t("skver.warn.no_metadata", name=skill_name))
                    return

            # 更新 metrics
            metrics = metadata.metrics
            total_calls = metrics.get("total_calls", 0) + 1
            if success:
                success_calls = metrics.get("success_calls", 0) + 1
                consecutive_failures = 0
            else:
                success_calls = metrics.get("success_calls", 0)
                consecutive_failures = metrics.get("consecutive_failures", 0) + 1

            metrics["total_calls"] = total_calls
            metrics["success_calls"] = success_calls
            metrics["consecutive_failures"] = consecutive_failures
            metrics["last_used"] = datetime.now().isoformat()

            # 计算新分数
            old_score = metadata.score
            if success:
                new_score = min(100, old_score + self.SUCCESS_INCREMENT)
            else:
                new_score = max(0, old_score - self.FAILURE_PENALTY)
            metadata.score = new_score

            metadata.updated_at = datetime.now()

            logger.debug(
                _skver_t(
                    "skver.debug.score_update",
                    name=skill_name,
                    s=new_score,
                    ok=success,
                    cf=consecutive_failures,
                )
            )

            # 【保留】检查是否达到本能固化条件
            if self.is_instinct(skill_name):
                logger.info(
                    _skver_t(
                        "skver.log.instinct_threshold",
                        name=skill_name,
                        u=total_calls,
                        s=new_score,
                    )
                )

    def _instinct_py_on_disk(self, skill_name: str) -> bool:
        """``instincts/`` 目录下已有同名 .py 时视为已固化本能（与使用率阈值无关）。"""
        base = getattr(self.evolution_engine, "instincts_dir", None)
        if not base or not os.path.isdir(base):
            return False
        sn = skill_name.upper()
        for name in (f"{sn.lower()}.py", f"{sn}.py"):
            if os.path.isfile(os.path.join(base, name)):
                return True
        return False

    def is_instinct(self, skill_name: str) -> bool:
        """判断技能是否为本能（Instinct）—— 包含第四阶段 TDD 最终条件"""
        skill_name = skill_name.upper()
        if self._instinct_py_on_disk(skill_name):
            return True
        metadata = self._metadata_cache.get(skill_name)
        if not metadata:
            return False

        total_uses = metadata.metrics.get("total_calls", 0)
        score = metadata.score
        consecutive_failures = metadata.metrics.get("consecutive_failures", 0)
        tdd_consecutive_passes = metadata.metrics.get("tdd_consecutive_passes", 0)

        # 原有条件
        classic_instinct = (
            total_uses >= self.INSTINCT_MIN_USES
            and score >= self.INSTINCT_MIN_SCORE
            and consecutive_failures <= self.INSTINCT_MAX_CONSECUTIVE_FAILURES
        )

        # 第四阶段最终本能固化条件（更严格）
        final_instinct = (
            total_uses >= self.INSTINCT_TDD_MIN_TOTAL_CALLS
            and score >= self.INSTINCT_TDD_MIN_SCORE
            and tdd_consecutive_passes >= self.INSTINCT_TDD_MIN_CONSECUTIVE_PASSES
        )

        is_instinct = classic_instinct or final_instinct

        if is_instinct:
            logger.info(
                _skver_t(
                    "skver.log.instinct_marked",
                    name=skill_name,
                    u=total_uses,
                    s=score,
                    tp=tdd_consecutive_passes,
                )
            )

        return is_instinct

    # ====================== 【步骤 2.3 新增】Protected 标记支持 ======================
    def is_protected(self, skill_name: str) -> bool:
        """判断技能是否被标记为 protected（CodeQualityScorer 保守决策使用）"""
        skill_name = skill_name.upper()
        metadata = self._metadata_cache.get(skill_name)
        if not metadata:
            return False
        return getattr(metadata, "status", None) == "protected"

    async def mark_as_protected(self, skill_name: str) -> None:
        """将技能标记为 protected（供 SkillOptimizer 调用）"""
        skill_name = skill_name.upper()
        async with self._cache_lock:
            metadata = self._metadata_cache.get(skill_name)
            if not metadata:
                metadata = await self._get_skill_metadata_from_db(skill_name)
                if not metadata:
                    metadata = SkillMetadata(
                        skill_name=skill_name,
                        current_version="v1.0",
                        versions={
                            "v1.0": SkillVersion(
                                version="v1.0",
                                code="",
                                score=100.0,
                                reason="auto-created for protected mark",
                            )
                        },
                    )
                self._metadata_cache[skill_name] = metadata

            metadata.status = "protected"
            metadata.updated_at = datetime.now()
            await self._flush_to_memory(skill_name, metadata)
            logger.info(_skver_t("skver.log.protected", name=skill_name))

    # =================================================================================

    async def get_skill_status(self, skill_name: str) -> Tuple[str, float, int]:
        """从缓存获取技能评分和连续失败次数（支持 protected 状态）"""
        skill_name = skill_name.upper()
        async with self._cache_lock:
            metadata = self._metadata_cache.get(skill_name)
            if metadata:
                status = getattr(metadata, "status", "active")
                return status, metadata.score, metadata.metrics.get("consecutive_failures", 0)

        metadata = await self._get_skill_metadata_from_db(skill_name)
        if metadata:
            async with self._cache_lock:
                self._metadata_cache[skill_name] = metadata
            status = getattr(metadata, "status", "active")
            return status, metadata.score, metadata.metrics.get("consecutive_failures", 0)
        return "unknown", 0.0, 0

    async def get_skills_needing_optimization(self) -> List[str]:
        """
        返回所有需要优化的技能名称列表（跳过 instinct 和 protected 技能）
        """
        async with self._cache_lock:
            return [
                name
                for name, meta in self._metadata_cache.items()
                if not self.is_instinct(name)
                and not self.is_protected(name)
                and (
                    meta.score <= self.SCORE_THRESHOLD_OPTIMIZATION
                    or meta.metrics.get("consecutive_failures", 0)
                    >= self.CONSECUTIVE_FAILURE_THRESHOLD
                )
            ]

    async def _flush_to_memory(self, skill_name: str, metadata: SkillMetadata):
        """刷盘到 LayeredMemory"""
        try:
            payload = metadata.model_dump() if hasattr(metadata, "model_dump") else vars(metadata)
            await self.memory.store_experience(
                trace_id=f"skill_meta_{skill_name}_{int(datetime.now().timestamp())}",
                domain="skill_metadata",
                payload=payload,
                chat_id="system",
            )
        except Exception as e:
            logger.error(_skver_t("skver.err.flush", e=e))

    async def _get_skill_metadata_from_db(self, skill_name: str) -> Optional[SkillMetadata]:
        """直接从数据库读取指定技能的元数据（回退用）"""
        all_metadata = await self.memory.retrieve_recent(
            domain="skill_metadata", limit=1000, chat_id="system"
        )
        for meta in all_metadata:
            if meta.get("skill_name") == skill_name:
                try:
                    return SkillMetadata.model_validate(meta)
                except Exception as e:
                    logger.error(_skver_t("skver.warn.parse_meta", e=e))
                    return None
        return None


# --- END OF FILE skill_version_manager.py ---
