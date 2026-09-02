# src/adami_kernel/market/skill_market.py
# --- START OF FILE skill_market.py ---
import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from adami_kernel.config import settings
from adami_kernel.cortex.evolution import EvolutionEngine
from adami_kernel.cortex.meta_cortex import MetaCortex
from adami_kernel.i18n import t
from adami_kernel.market.github_hunter import GitHubHunter
from adami_kernel.market.melter import SkillMelter
from adami_kernel.cortex.endocrine import status_or_normal

logger = logging.getLogger("AdamI-SkillMarket")


def _mk_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class SkillMarket:
    """
    AdamI 技能市场核心引擎（工业级）
    已永久解决：上传后不显示 + 动态技能库消失 + bad escape + 删除失败 + 幽灵技能显示
    【本次核心修复】：GitHubHunter 正确注入 router（解决启动崩溃）
    【本次增强】：list_all_skills 双保险（get_all_skills + 直接遍历字典），确保前端始终有数据
    """

    def __init__(
        self,
        evolution_engine: EvolutionEngine,
        meta_cortex: Optional[MetaCortex] = None,
        router=None,
        endocrine=None,
    ):
        self.evolution = evolution_engine
        self.meta_cortex = meta_cortex
        self.router = router
        self.endocrine = endocrine

        # ====================== 【关键修复】GitHubHunter 必须传入 router ======================
        if router is None:
            logger.warning(_mk_t("skmkt.warn.no_router"))
        self.github_hunter = GitHubHunter(router) if router is not None else GitHubHunter(router)
        # ==============================================================================

        self.melter = SkillMelter(evolution_engine)

        self.market_cache: Dict[str, Any] = {}
        self.install_history: Dict[str, dict] = {}
        self.data_dir = settings.path_skill_market_dir
        os.makedirs(self.data_dir, exist_ok=True)

        # ====================== 缓存机制 ======================
        self._total_count = 0
        self._skills_cache: List[Dict] = []
        # ======================================================

        self._load_install_history()
        logger.info(_mk_t("skmkt.log.ready"))

    def _load_install_history(self):
        history_file = os.path.join(self.data_dir, "install_history.json")
        if os.path.exists(history_file):
            try:
                with open(history_file, "r", encoding="utf-8") as f:
                    self.install_history = json.load(f)
            except Exception as e:
                logger.warning(_mk_t("skmkt.warn.load_hist", e=e))

    def _save_install_history(self):
        history_file = os.path.join(self.data_dir, "install_history.json")
        try:
            with open(history_file, "w", encoding="utf-8") as f:
                json.dump(self.install_history, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(_mk_t("skmkt.err.save_hist", e=e))

    async def list_all_skills(self) -> List[Dict]:
        """【最终核心修复】真实技能列表 - 双保险读取（优先 get_all_skills + 直接遍历字典）"""
        current_count = len(self.evolution.dynamic_skills) + len(self.evolution.core_instincts)

        # 缓存命中
        if self._skills_cache and self._total_count == current_count:
            logger.debug(_mk_t("skmkt.debug.cache_hit", n=current_count))
            return self._skills_cache

        skills = []

        # 优先使用 evolution 的 get_all_skills（兼容原有实现）
        if hasattr(self.evolution, "get_all_skills") and callable(self.evolution.get_all_skills):
            try:
                base_skills = self.evolution.get_all_skills()
                for base in base_skills:
                    name = base["name"]
                    history_info = self.install_history.get(name.upper(), {})
                    skill_entry = {
                        "name": name,
                        "type": base.get("type", "dynamic"),
                        "status": base.get("status", "active"),
                        "source": history_info.get(
                            "source", "system" if base.get("type") == "instinct" else "local"
                        ),
                        "installed_at": history_info.get(
                            "installed_at",
                            _mk_t("market.list.installed_builtin")
                            if base.get("type") == "instinct"
                            else _mk_t("market.list.unknown_time"),
                        ),
                        "description": base.get("description", _mk_t("market.list.no_description")),
                        "stars": base.get("stars", 0),
                        "usage": base.get("usage", 0),
                        "last_used": base.get("last_used", _mk_t("market.list.last_used_unknown")),
                    }
                    skills.append(skill_entry)
            except Exception as e:
                logger.warning(_mk_t("skmkt.warn.get_skills", e=e))

        # Fallback：直接遍历字典（最可靠方式）
        if not skills:
            # 动态技能
            for name, _skill in self.evolution.dynamic_skills.items():
                history = self.install_history.get(name.upper(), {})
                skills.append(
                    {
                        "name": name,
                        "type": "dynamic",
                        "status": "active",
                        "source": history.get("source", "local"),
                        "installed_at": history.get(
                            "installed_at", _mk_t("market.list.unknown_time")
                        ),
                        "description": history.get(
                            "description", _mk_t("market.list.desc_dynamic_default")
                        ),
                        "stars": history.get("stars", 0),
                        "usage": 0,
                        "last_used": _mk_t("market.list.last_used_unknown"),
                    }
                )
            # 本能技能
            for name, _skill in self.evolution.core_instincts.items():
                history = self.install_history.get(name.upper(), {})
                skills.append(
                    {
                        "name": name,
                        "type": "instinct",
                        "status": "active",
                        "source": "system",
                        "installed_at": _mk_t("market.list.installed_builtin"),
                        "description": history.get(
                            "description", _mk_t("market.list.desc_instinct_default")
                        ),
                        "stars": history.get("stars", 0),
                        "usage": 0,
                        "last_used": _mk_t("market.list.last_used_unknown"),
                    }
                )

        # 更新缓存
        self._skills_cache = skills
        self._total_count = current_count

        logger.info(
            _mk_t(
                "skmkt.log.list_built",
                n=len(skills),
                dyn=len(self.evolution.dynamic_skills),
                ins=len(self.evolution.core_instincts),
            )
        )
        return skills

    async def search_skills(self, query: str) -> List[Dict]:
        all_skills = await self.list_all_skills()
        query = query.lower()
        return [s for s in all_skills if query in s["name"].lower()]

    async def install_skill(
        self, skill_name: str, source: str = "github", repo_url: Optional[str] = None
    ) -> Dict:
        normalized_name = skill_name.upper()
        if (
            normalized_name in self.evolution.dynamic_skills
            or normalized_name in self.evolution.core_instincts
        ):
            logger.warning(_mk_t("skmkt.warn.already", name=skill_name))
            return {
                "status": "error",
                "error": _mk_t("market.error.skill_already_installed", skill_name=skill_name),
                "already_installed": True,
            }

        try:
            if source == "github" and repo_url:
                code = await self.github_hunter.fetch_code(repo_url)
                if not code or len(code.strip()) < 50:
                    return {"status": "error", "error": _mk_t("market.error.github_code_invalid")}
                melted_code = await self.melter.melt(code, skill_name)
                if melted_code is None:
                    return {"status": "error", "error": _mk_t("market.error.melt_failed")}
            else:
                melted_code = "result = 'installed'"

            result = await self.evolution.create_new_skill(
                skill_name=skill_name,
                description=_mk_t("market.install.description_from", source=source),
                code=melted_code,
            )
            if not isinstance(result, dict) or result.get("status") not in (None, "success"):
                err = (
                    (result.get("error") if isinstance(result, dict) else None)
                    or (result.get("reason") if isinstance(result, dict) else None)
                    or _mk_t("market.error.create_skill_failed")
                )
                return {"status": "error", "error": err, "data": result}

            self.install_history[normalized_name] = {
                "installed_at": datetime.now().isoformat(),
                "source": source,
                "repo_url": repo_url,
            }
            self._save_install_history()

            self._total_count += 1
            self._skills_cache = []

            logger.info(_mk_t("skmkt.log.install_ok", name=skill_name))
            return {"status": "success", **result}

        except Exception as e:
            logger.error(_mk_t("skmkt.err.install", name=skill_name, e=e))
            return {"status": "error", "error": str(e)}

    async def get_recommendations(self, limit: int = 5) -> List[Dict]:
        if not self.meta_cortex:
            return []
        try:
            plan = await self.meta_cortex.evaluate_and_plan(
                current_persona=META_CORTEX_PERSONA,
                endocrine_status=status_or_normal(self.endocrine),
            )
            genome_plan = plan.get("genome_plan", []) if isinstance(plan, dict) else []
            recommendations = []
            for target in genome_plan[:limit]:
                # UI/安装需要“可用 skill_name”；同时保留人类可读 title（可能为中文）
                inferred_skill_name = (
                    re.sub(r"[^A-Z0-9_]", "_", target.upper()).strip("_")[:30] or "META_CORTEX_REC"
                )
                recommendations.append(
                    {
                        "skill_name": inferred_skill_name,
                        "title": target,
                        "repo_url": None,
                        "reason": _mk_t("market.recommend.reason", target=target),
                        "category": "general",
                        "confidence": 0.85,
                    }
                )
            return recommendations
        except Exception as e:
            logger.error(_mk_t("skmkt.err.recommend", e=e))
            return []

    async def upload_custom_skill(
        self, skill_name: str, description: str = "", code: str = ""
    ) -> Dict[str, Any]:
        if not skill_name or not code.strip():
            return {
                "status": "error",
                "error": _mk_t("market.error.name_code_empty"),
                "skill_name": skill_name,
                "melted": False,
            }

        normalized_name = skill_name.upper()
        if (
            normalized_name in self.evolution.dynamic_skills
            or normalized_name in self.evolution.core_instincts
        ):
            return {
                "status": "error",
                "error": _mk_t("market.error.skill_exists", skill_name=skill_name),
                "skill_name": skill_name,
                "melted": False,
            }

        try:
            clean_code = code.strip()
            clean_code = re.sub(r"\\s", " ", clean_code)
            clean_code = re.sub(r"\\\\s", " ", clean_code)
            clean_code = re.sub(r"\\([a-zA-Z])", r"\\\\\1", clean_code)
            clean_code = re.sub(r"\\n", "\n", clean_code)
            clean_code = re.sub(r"\\t", "\t", clean_code)
            clean_code = re.sub(r"\\r", "\r", clean_code)
            clean_code = clean_code.replace("{", "{{").replace("}", "}}")

            melted_code = await self.melter.melt(clean_code, skill_name)
            if melted_code is None:
                return {
                    "status": "error",
                    "error": _mk_t("market.error.melt_failed"),
                    "skill_name": skill_name,
                    "melted": False,
                }

            await self.evolution.create_new_skill(
                skill_name=skill_name,
                description=description
                or _mk_t("market.upload.description_user", skill_name=skill_name),
                code=melted_code,
            )

            self.install_history[normalized_name] = {
                "installed_at": datetime.now().isoformat(),
                "source": "user_upload",
                "method": "custom",
            }
            self._save_install_history()

            self._total_count += 1
            self._skills_cache = []

            logger.info(_mk_t("skmkt.log.upload_ok", name=skill_name))
            return {
                "status": "success",
                "message": _mk_t("market.upload.success_message", skill_name=skill_name),
                "skill_name": skill_name,
                "melted": True,
            }

        except Exception as e:
            logger.error(_mk_t("skmkt.err.upload", name=skill_name, e=e), exc_info=True)
            return {"status": "error", "error": str(e), "skill_name": skill_name, "melted": False}

    async def delete_skill(self, name: str) -> bool:
        """【修复】改为 async，彻底清理动态技能 + 历史记录"""
        upper_name = name.upper()
        try:
            if upper_name in self.evolution.dynamic_skills:
                del self.evolution.dynamic_skills[upper_name]
                logger.info(_mk_t("skmkt.log.del_dyn", name=name))

            if upper_name in self.install_history:
                del self.install_history[upper_name]
                self._save_install_history()
                logger.info(_mk_t("skmkt.log.del_hist", name=name))

            self._skills_cache = []
            self._total_count = len(self.evolution.dynamic_skills) + len(
                self.evolution.core_instincts
            )

            logger.info(_mk_t("skmkt.log.del_ok", name=name))
            return True
        except Exception as e:
            logger.error(_mk_t("skmkt.err.del", name=name, e=e))
            return False

    async def get_market_stats(self) -> Dict:
        return {
            "total_skills": len(self.evolution.dynamic_skills) + len(self.evolution.core_instincts),
            "dynamic_count": len(self.evolution.dynamic_skills),
            "instinct_count": len(self.evolution.core_instincts),
            "last_install": max(
                (v.get("installed_at") for v in self.install_history.values()),
                default=_mk_t("market.stats.never"),
            ),
        }


# --- END OF FILE skill_market.py ---
