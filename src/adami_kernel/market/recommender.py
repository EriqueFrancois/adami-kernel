import logging
import re
from typing import Dict, List, Optional

from adami_kernel.config import settings
from adami_kernel.cortex.evolution import EvolutionEngine
from adami_kernel.cortex.meta_cortex import MetaCortex
from adami_kernel.i18n import t as i18n_t
from adami_kernel.market.github_hunter import GitHubHunter

logger = logging.getLogger("AdamI-SkillRecommender")


def _reco_t(key: str, **kwargs: object) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


class SkillRecommender:
    """
    AdamI 技能智能推荐引擎（MetaCortex + GitHubHunter 双驱动）
    功能：
    - 分析当前技能短板（MetaCortex 长期规划）
    - 从 GitHub 猎手获取高分候选仓库
    - 生成带优先级 + 理由的推荐列表
    - 支持按领域（AI/Web/Crypto 等）过滤
    """

    def __init__(
        self,
        meta_cortex: MetaCortex,
        github_hunter: GitHubHunter,
        evolution_engine: EvolutionEngine,
    ):
        self.meta_cortex = meta_cortex
        self.github_hunter = github_hunter
        self.evolution = evolution_engine
        logger.info(_reco_t("reco.log.active"))

    async def get_recommendations(
        self, limit: int = 8, category: Optional[str] = None
    ) -> List[Dict]:
        """
        生成智能技能推荐列表
        返回格式：[{name, repo_url, score, reason, category, confidence}, ...]
        """
        # Step 1: MetaCortex 分析当前能力短板
        current_persona = await self._get_current_persona_summary()
        endocrine_status = "normal"  # 可后续扩展为真实内分泌状态

        plan = await self.meta_cortex.evaluate_and_plan(
            current_persona=current_persona, endocrine_status=endocrine_status
        )

        # Step 2: 从 MetaCortex 的 genome_plan 中提取推荐方向
        targets = plan.get("genome_plan", []) if isinstance(plan, dict) else []
        if not targets:
            targets = ["AI agent", "web automation", "crypto tools"]  # 兜底

        recommendations = []

        for target in targets[:limit]:
            # Step 3: 调用 GitHubHunter 搜索最匹配仓库
            repos = await self.github_hunter.search_repos(
                query=target, category=category, min_stars=3000, limit=3
            )

            if not repos:
                continue

            # 取评分最高的一个
            best = max(repos, key=lambda x: x.get("score", 0))

            recommendations.append(
                {
                    "name": best["name"].split("/")[-1],
                    "full_name": best["name"],
                    "repo_url": best["url"],
                    "stars": best["stars"],
                    "score": best["score"],
                    "reason": _reco_t("reco.reason.row", target=target),
                    "category": category or "general",
                    "confidence": round(best["score"] / 10, 1),
                    "suggested_skill_name": self._generate_skill_name(best["name"]),
                    "description": best.get("description", _reco_t("reco.desc.none")),
                }
            )

        # 按 confidence 降序排序
        recommendations.sort(key=lambda x: x["confidence"], reverse=True)

        logger.info(_reco_t("reco.log.count", n=len(recommendations)))
        return recommendations[:limit]

    async def _get_current_persona_summary(self) -> str:
        """获取当前系统能力简要总结"""
        dynamic = len(self.evolution.dynamic_skills)
        instincts = len(self.evolution.core_instincts)
        return _reco_t("reco.summary.persona", dynamic=dynamic, instincts=instincts)

    def _generate_skill_name(self, repo_name: str) -> str:
        """从仓库名生成合法的技能名称"""
        name = repo_name.split("/")[-1]
        name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
        return name.upper()[:40]

    async def close(self):
        """清理资源"""
        await self.github_hunter.close()
