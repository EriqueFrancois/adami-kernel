# src/adami_kernel/skill_manager/code_quality_scorer.py
"""
AdamI Skill Manager - CodeQualityScorer（新旧代码对比评价引擎）

工业级混合评分系统：
- 规则引擎：量化代码质量指标
- LLM 审查：语义对比（功能完整性、可维护性等）
- 输出结构化 CodeQualityScore，用于 SkillOptimizer 决策
"""

import ast
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from adami_kernel.config import settings
from adami_kernel.cortex.router import LLMRouter
from adami_kernel.hippocampus.episodic_memory import EpisodicMemory
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.boot_msg import boot_t

logger = logging.getLogger("AdamI-CodeQualityScorer")


def _cqsc_t(key: str, **kwargs: Any) -> str:
    return i18n_t(key, locale=settings.effective_ui_default_locale(), **kwargs)


@dataclass
class CodeQualityScore:
    """代码质量评分结果（0-100分）"""

    total_score: float
    functionality: float  # 功能完整性 40%
    robustness: float  # 鲁棒性/容错性 25%
    code_quality: float  # 代码质量/可读性 15%
    performance: float  # 性能/效率 10%
    security: float  # 安全性 10%
    details: Dict[str, Any]  # 详细指标
    recommendation: str  # 优化建议


class CodeQualityScorer:
    """新旧代码对比评价引擎"""

    def __init__(self, router: LLMRouter, episodic_memory: EpisodicMemory):
        self.router = router
        self.episodic_memory = episodic_memory
        logger.info(boot_t("boot.log.code_quality_scorer_init"))

    async def score_code(
        self, code: str, skill_name: str, old_code: Optional[str] = None
    ) -> CodeQualityScore:
        """对单段代码进行完整评分（支持新旧对比）"""
        rule_score = self._rule_based_scoring(code, skill_name)

        # 如果有旧代码，进行 LLM 语义对比
        llm_score = (
            await self._llm_based_review(code, old_code, skill_name) if old_code else rule_score
        )

        # 融合得分（规则 60% + LLM 40%）
        total = round(0.6 * rule_score.total_score + 0.4 * llm_score.total_score, 2)

        final_score = CodeQualityScore(
            total_score=total,
            functionality=max(rule_score.functionality, llm_score.functionality),
            robustness=max(rule_score.robustness, llm_score.robustness),
            code_quality=max(rule_score.code_quality, llm_score.code_quality),
            performance=max(rule_score.performance, llm_score.performance),
            security=max(rule_score.security, llm_score.security),
            details={
                "rule_score": rule_score.total_score,
                "llm_score": llm_score.total_score,
                "old_code_present": old_code is not None,
            },
            recommendation=llm_score.recommendation,
        )

        logger.info(
            _cqsc_t(
                "cqsc.log.score_done",
                skill_name=skill_name,
                total=final_score.total_score,
            )
        )
        return final_score

    def _rule_based_scoring(self, code: str, skill_name: str) -> CodeQualityScore:
        """规则引擎量化评分"""
        try:
            tree = ast.parse(code)
            lines = code.splitlines()

            # 功能完整性（是否有 execute、参数处理）
            has_execute = any(
                n.name == "execute" for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)
            )
            functionality = 90.0 if has_execute else 40.0

            # 鲁棒性（异常处理、重试）
            has_try = any(isinstance(n, ast.Try) for n in ast.walk(tree))
            robustness = 85.0 if has_try else 50.0

            # 代码质量（长度、注释、日志）
            code_quality = min(95.0, len(lines) * 0.8 + 30)

            # 性能（async + httpx）
            performance = 88.0 if "httpx" in code or "asyncio" in code else 65.0

            # 安全性（危险调用检查）
            security = (
                40.0
                if any(kw in code for kw in ["subprocess", "eval", "exec", "os.system"])
                else 95.0
            )

            total = round(
                0.4 * functionality
                + 0.25 * robustness
                + 0.15 * code_quality
                + 0.1 * performance
                + 0.1 * security,
                2,
            )

            return CodeQualityScore(
                total_score=total,
                functionality=functionality,
                robustness=robustness,
                code_quality=code_quality,
                performance=performance,
                security=security,
                details={"method": "rule_engine"},
                recommendation=_cqsc_t("cqsc.rec.rule_done"),
            )
        except Exception as e:
            logger.error(_cqsc_t("cqsc.log.rule_err", err=e))
            return CodeQualityScore(50.0, 50, 50, 50, 50, 50, {}, _cqsc_t("cqsc.rec.rule_fail"))

    async def _llm_based_review(
        self, new_code: str, old_code: str, skill_name: str
    ) -> CodeQualityScore:
        """LLM 语义对比审查（think 脑）"""
        prompt = _cqsc_t(
            "cqsc.prompt.review",
            skill_name=skill_name,
            old_snippet=old_code[:2000],
            new_snippet=new_code[:2000],
        )

        try:
            response = await self.router.call_llm(
                prompt, brain_type="think", temperature=0.0, max_tokens=800
            )
            data = self._extract_json(response)  # 使用已有的 json_parser

            return CodeQualityScore(
                total_score=round(
                    (
                        data.get("functionality", 50)
                        + data.get("robustness", 50)
                        + data.get("code_quality", 50)
                        + data.get("performance", 50)
                        + data.get("security", 50)
                    )
                    / 5,
                    2,
                ),
                functionality=float(data.get("functionality", 50)),
                robustness=float(data.get("robustness", 50)),
                code_quality=float(data.get("code_quality", 50)),
                performance=float(data.get("performance", 50)),
                security=float(data.get("security", 50)),
                details={"method": "llm_review"},
                recommendation=data.get("recommendation", _cqsc_t("cqsc.rec.llm_done")),
            )
        except Exception as e:
            logger.warning(_cqsc_t("cqsc.log.llm_fallback", err=e))
            return self._rule_based_scoring(new_code, skill_name)

    def _extract_json(self, text: str) -> Dict[str, Any]:
        """复用已有的 JSON 提取逻辑"""
        from adami_kernel.cortex.tools.json_parser import extract_json_from_llm_output

        return extract_json_from_llm_output(text) or {}


# --- END OF FILE code_quality_scorer.py ---
