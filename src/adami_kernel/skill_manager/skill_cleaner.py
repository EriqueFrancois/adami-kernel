# src/adami_kernel/skill_manager/skill_cleaner.py
# --- START OF FILE skill_cleaner.py ---

import asyncio
import logging
import os
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from adami_kernel.skill_manager.skill_version_manager import SkillVersionManager
    from adami_kernel.skill_manager.vector_store import VectorStore

from adami_kernel.config import settings
from adami_kernel.cortex.evolution import EvolutionEngine
from adami_kernel.hippocampus.layered_memory import LayeredMemory
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t

logger = logging.getLogger("AdamI-SkillCleaner")


def _skclr_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class SkillCleaner:
    """
    技能库清理员（Phase 4）
    负责定期扫描并清理：
    - 低分废弃技能（status=deprecated, score<30）【临时禁用】
    - 长期闲置技能（创建超过7天，调用次数<3）
    - 无主文件（技能文件存在但元数据中无对应记录）
    - 【Phase 1 新增】污染假技能（长中文名、VectorStore 残留）
    【本次 v2.1 修复】：与 SkillVersionManager / SkillManager 完全对齐，get_skill_metadata 调用增加 AttributeError 优雅降级
    """

    def __init__(
        self,
        memory: LayeredMemory,
        evolution_engine: EvolutionEngine,
        vector_store: Optional["VectorStore"] = None,
        skill_version_manager: Optional["SkillVersionManager"] = None,
    ):
        self.memory = memory
        self.evolution = evolution_engine
        self.vector_store = vector_store
        self.skill_version_manager = skill_version_manager

        # 【Phase 1 新增】污染假技能检测正则（与 SkillRouter 完全一致）
        self.pollution_pattern = re.compile(r"[\u4e00-\u9fff]{5,}")  # 包含5个以上中文字符

        logger.info(boot_t("boot.log.skill_cleaner_init"))

    async def clean(self) -> None:
        """执行清理主流程"""
        logger.info(boot_t("boot.log.skill_cleaner_task_start"))
        # 1. 加载所有技能元数据
        all_metadata = await self._load_metadata()
        if not all_metadata:
            logger.info(boot_t("boot.log.skill_cleaner_no_metadata"))
            return

        # 2. 找出需要删除的技能（原有低分/闲置规则）
        to_delete = await self._find_skills_to_delete(all_metadata)
        for skill_name in to_delete:
            await self._delete_skill(skill_name)

        # 3. 清理无主文件（原有逻辑）
        await self._clean_orphaned_files(all_metadata)

        # 【Phase 1 新增】清理污染假技能（VectorStore + SkillRouter 残留）
        await self._cleanup_polluted_candidates()

        logger.info(boot_t("boot.log.skill_cleaner_done", count=len(to_delete)))

    async def _load_metadata(self) -> List[Dict[str, Any]]:
        """从 LayeredMemory 加载所有技能元数据"""
        records = await self.memory.retrieve_recent(
            domain="skill_metadata", limit=1000, chat_id="system"
        )
        # LayeredMemory.retrieve_recent：SQL 按 id DESC 取行后再 [::-1]，返回列表为**时间正序**（旧→新）。
        # 同一 skill_name 多条记录时须**以后覆盖前**，保留最新一条。
        latest: Dict[str, Dict[str, Any]] = {}
        for meta in records or []:
            skill_name = (meta.get("skill_name") or "").strip().upper()
            if not skill_name:
                continue
            latest[skill_name] = meta
        return list(latest.values())

    async def _find_skills_to_delete(self, all_metadata: List[Dict]) -> List[str]:
        """根据规则筛选待删除的技能名列表"""
        to_delete = []
        now = datetime.now()

        for meta in all_metadata:
            skill_name = meta.get("skill_name")
            if not skill_name:
                continue
            # 已删除的技能不应重复标记
            if str(meta.get("status") or "").lower() == "deleted":
                continue

            # ====================== 【临时禁用】低分废弃技能删除 ======================
            # 规则1：低分废弃（暂时禁用，防止误删新技能）
            # status = meta.get("status")
            # score = meta.get("score", 100)
            # if status == "deprecated" and score < 30:
            #     logger.info(f"[SkillCleaner][UnifiedIntent] 标记删除: 低分废弃技能 {skill_name} (score={score})")
            #     to_delete.append(skill_name)
            #     continue
            # ========================================================================

            # 规则2：长期闲置（创建超过7天且总调用次数<3）
            created_at = meta.get("created_at")
            if created_at:
                try:
                    created = datetime.fromisoformat(created_at)
                    days_old = (now - created).days
                except (ValueError, TypeError):
                    days_old = 0
                total_calls = meta.get("metrics", {}).get("total_calls", 0)
                if days_old > 7 and total_calls < 3:
                    logger.info(
                        _skclr_t(
                            "skclr.log.mark_idle",
                            name=skill_name,
                            ca=created_at,
                            tc=total_calls,
                        )
                    )
                    to_delete.append(skill_name)

        return to_delete

    async def _delete_skill(self, skill_name: str) -> None:
        """物理删除技能文件、内存中的技能对象，并更新元数据为 deleted，从向量存储中移除（带重试）"""
        skill_name_upper = skill_name.upper()
        skill_name_lower = skill_name.lower()

        # 从 EvolutionEngine 内存中移除
        self.evolution.dynamic_skills.pop(skill_name_upper, None)
        self.evolution.core_instincts.pop(skill_name_upper, None)

        # 从工具注册表中移除
        if skill_name_upper in self.evolution.tool_schemas:
            del self.evolution.tool_schemas[skill_name_upper]

        # 删除技能文件（动态目录与本能目录；文件名可能为大写或小写）
        _paths = [
            os.path.join(self.evolution.skills_dir, f"{skill_name_lower}.py"),
            os.path.join(self.evolution.skills_dir, f"{skill_name_upper}.py"),
            os.path.join(self.evolution.instincts_dir, f"{skill_name_lower}.py"),
            os.path.join(self.evolution.instincts_dir, f"{skill_name_upper}.py"),
        ]
        for file_path in _paths:
            if os.path.exists(file_path):
                for attempt in range(2):
                    try:
                        os.remove(file_path)
                        logger.info(_skclr_t("skclr.log.file_deleted", path=file_path))
                        break
                    except Exception as e:
                        logger.warning(
                            _skclr_t(
                                "skclr.warn.del_retry",
                                a=attempt + 1,
                                path=file_path,
                                e=e,
                            )
                        )
                        await asyncio.sleep(0.5)
                else:
                    logger.error(_skclr_t("skclr.err.del_final", path=file_path))

        # ====================== 【v2.1 核心修复】更新元数据状态为 deleted ======================
        # SkillVersionManager.get_skill_metadata 方法不存在 → 优雅降级，直接使用 memory 追加 deleted 记录
        if self.skill_version_manager:
            try:
                metadata = await self.skill_version_manager.get_skill_metadata(skill_name_upper)
                if metadata:
                    metadata.status = "deleted"
                    metadata.updated_at = datetime.now()
                    await self._replace_skill_metadata(skill_name_upper, metadata.model_dump())
                    logger.info(boot_t("boot.log.skill_cleaner_metadata_deleted", name=skill_name))
                else:
                    logger.warning(_skclr_t("skclr.warn.no_meta", name=skill_name))
            except AttributeError:
                logger.warning(_skclr_t("skclr.warn.no_get_metadata"))
                # 直接使用 memory 追加 deleted 记录（与 SkillManager 完全对齐）
                await self._replace_skill_metadata(
                    skill_name_upper,
                    {
                        "skill_name": skill_name_upper,
                        "status": "deleted",
                        "updated_at": datetime.now().isoformat(),
                    },
                )
            except Exception as e:
                logger.error(_skclr_t("skclr.err.meta_update", name=skill_name, e=e))
        else:
            logger.warning(_skclr_t("skclr.warn.svm_none"))

        # ====================== 【核心修复】从向量存储中移除（带重试） ======================
        if self.vector_store:
            for attempt in range(2):
                try:
                    await self.vector_store.remove_skill(skill_name_upper)
                    logger.info(boot_t("boot.log.skill_cleaner_vector_removed", name=skill_name))
                    break
                except Exception as e:
                    logger.warning(_skclr_t("skclr.warn.vs_retry", a=attempt + 1, e=e))
                    await asyncio.sleep(0.5)
            else:
                logger.error(_skclr_t("skclr.err.vs_final", name=skill_name))
        else:
            logger.warning(_skclr_t("skclr.warn.vs_none"))

    async def _replace_skill_metadata(self, skill_name: str, new_payload: Dict[str, Any]) -> None:
        """辅助方法：追加一条技能元数据记录（状态为 deleted）"""
        domain = "skill_metadata"
        await self.memory.store_experience(
            trace_id=f"skill_metadata_{skill_name}_deleted_{int(datetime.now().timestamp())}",
            domain=domain,
            payload=new_payload,
            chat_id="system",
        )
        logger.debug(_skclr_t("skclr.debug.meta_deleted_row", name=skill_name))

    async def _clean_orphaned_files(self, all_metadata: List[Dict]) -> None:
        """删除无对应元数据的技能文件"""
        existing_names = set()
        for meta in all_metadata:
            skill_name = meta.get("skill_name")
            status = meta.get("status")
            if skill_name and status != "deleted":
                existing_names.add(skill_name.upper())

        for directory in [self.evolution.skills_dir, self.evolution.instincts_dir]:
            if not os.path.exists(directory):
                continue
            for filename in os.listdir(directory):
                if not filename.endswith(".py"):
                    continue
                skill_name = filename[:-3].upper()
                if skill_name not in existing_names:
                    file_path = os.path.join(directory, filename)
                    for attempt in range(2):
                        try:
                            os.remove(file_path)
                            logger.info(_skclr_t("skclr.log.orphan_deleted", path=file_path))
                            break
                        except Exception as e:
                            logger.warning(
                                _skclr_t(
                                    "skclr.warn.orphan_retry",
                                    a=attempt + 1,
                                    path=file_path,
                                    e=e,
                                )
                            )
                            await asyncio.sleep(0.5)
                    else:
                        logger.error(_skclr_t("skclr.err.orphan_final", path=file_path))

    # ====================== 【Phase 1 新增】污染假技能清理 ======================
    async def _cleanup_polluted_candidates(self):
        """清理 VectorStore / SkillRouter 中的污染假技能（长中文名）"""
        if not self.vector_store:
            logger.warning(_skclr_t("skclr.warn.pollution_vs"))
            return

        logger.info(boot_t("boot.log.skill_cleaner_pollution_scan"))

        # 获取所有技能（fallback 模式下使用 search）
        try:
            all_skills = await self.vector_store.search("")  # 空查询返回全部
        except Exception:
            logger.warning(_skclr_t("skclr.warn.pollution_list"))
            return

        polluted_count = 0
        for skill in all_skills:
            name = skill.get("skill_name", "")
            if self._is_polluted_name(name):
                logger.warning(boot_t("boot.log.skill_cleaner_pollution_found", name=name))
                await self._delete_skill(name)
                polluted_count += 1

        if polluted_count > 0:
            logger.info(boot_t("boot.log.skill_cleaner_pollution_cleaned", count=polluted_count))
        else:
            logger.info(boot_t("boot.log.skill_cleaner_pollution_none"))

    def _is_polluted_name(self, name: str) -> bool:
        """判断是否为污染假技能（与 SkillRouter 完全一致）"""
        if len(name) > 30:
            return True
        if self.pollution_pattern.search(name):
            return True
        return False


# --- END OF FILE src/adami_kernel/skill_manager/skill_cleaner.py ---
# 文件路径：src/adami_kernel/skill_manager/skill_cleaner.py
# 版本：v2.1（SkillVersionManager 接口兼容 + get_skill_metadata 优雅降级版）
