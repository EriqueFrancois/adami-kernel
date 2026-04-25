# src/adami_kernel/cortex/intent_adaptive/rule_classifier.py
"""Rule-only intent hints for planner-bound tasks (System 1 extension; no LLM)."""

from __future__ import annotations

import re
from typing import Any, Optional

from adami_kernel.cortex.intent_adaptive.models import (
    IntentClassificationResult,
    IntentFamily,
    IntentType,
)

# Rule-based tier: fast path, no LLM. Confidence stays bounded so LLM / registry can override later.
RULE_CONFIDENCE_MAX: float = 0.6

_RE_REPORT_LEADER = re.compile(r"^/report(?:\s|$)", re.IGNORECASE)
_RE_WEATHER = re.compile(r"(weather|forecast|气温|天气|温度|降雨|下雪)", re.IGNORECASE)
_RE_CRYPTO = re.compile(
    r"(?:(?<![a-z0-9])(btc|bitcoin|eth|ethereum)(?![a-z0-9])|"
    r"比特币|以太坊|加密货币|数字货币|币\s*价|token\s+price|crypto\s+price)",
    re.IGNORECASE,
)
_RE_SYNTHESIS = re.compile(
    r"(调研|综述|摘要|总结|报告大纲|research\s+summary|write\s+a\s+summary|executive\s+summary)",
    re.IGNORECASE,
)
_RE_PLANNING = re.compile(
    r"(计划|规划|路线图|里程碑|roadmap|project\s+plan|step\s*by\s*step)",
    re.IGNORECASE,
)
_RE_GREETING = re.compile(r"^(hi|hello|hey|你好|您好)[\s!?，,。]*$", re.IGNORECASE)


def rule_classify_after_router(
    task_text: str,
    *,
    router_tag: str,
    router_data: Any,
) -> Optional[IntentClassificationResult]:
    """
    Propose a coarse ``IntentClassificationResult`` only when ``router_tag`` is
    ``COMPLEX_TASK`` (planner path). Never overrides ``SYSTEM_ACTION`` or
    ``DIRECT_ANSWER``. Returns ``None`` when no heuristic matches.

    Callers must run ``SemanticIntentRouter.route_task`` first and pass its ``tag`` /
    ``data`` here unchanged.
    """
    _ = router_data  # reserved for future disambiguation (e.g. multimodal hints)
    if router_tag != "COMPLEX_TASK":
        return None

    task = (task_text or "").strip()
    if not task:
        return None

    # Rule-based tier: fast path, no LLM — never relabel explicit /report commands.
    if _RE_REPORT_LEADER.match(task):
        return None

    if _RE_GREETING.match(task):
        return IntentClassificationResult(
            primary_family=IntentFamily.CONVERSATION,
            primary_type=IntentType.CONVERSATION_GREETING,
            confidence=RULE_CONFIDENCE_MAX,
            slots={"greeting": task[:64]},
            route="dynamic",
            reason_codes=["rule_based", "rule_hit_greeting"],
        )

    if _RE_WEATHER.search(task):
        return IntentClassificationResult(
            primary_family=IntentFamily.RETRIEVAL,
            primary_type=IntentType.RETRIEVAL_WEATHER,
            confidence=RULE_CONFIDENCE_MAX,
            slots={"query_excerpt": task[:256]},
            route="dynamic",
            reason_codes=["rule_based", "rule_hit_weather"],
        )

    if _RE_CRYPTO.search(task):
        return IntentClassificationResult(
            primary_family=IntentFamily.RETRIEVAL,
            primary_type=IntentType.RETRIEVAL_CRYPTO,
            confidence=RULE_CONFIDENCE_MAX,
            slots={"query_excerpt": task[:256]},
            route="dynamic",
            reason_codes=["rule_based", "rule_hit_crypto"],
        )

    if _RE_PLANNING.search(task):
        return IntentClassificationResult(
            primary_family=IntentFamily.PLANNING,
            primary_type=IntentType.PLANNING_GOAL,
            confidence=RULE_CONFIDENCE_MAX,
            slots={"query_excerpt": task[:256]},
            route="dynamic",
            reason_codes=["rule_based", "rule_hit_planning"],
        )

    if _RE_SYNTHESIS.search(task):
        return IntentClassificationResult(
            primary_family=IntentFamily.SYNTHESIS,
            primary_type=IntentType.SYNTHESIS_SUMMARY,
            confidence=RULE_CONFIDENCE_MAX,
            slots={"query_excerpt": task[:256]},
            route="dynamic",
            reason_codes=["rule_based", "rule_hit_synthesis"],
        )

    return None
