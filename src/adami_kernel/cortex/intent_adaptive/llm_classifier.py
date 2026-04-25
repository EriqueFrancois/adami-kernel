# src/adami_kernel/cortex/intent_adaptive/llm_classifier.py
"""Optional LLM-backed intent refinement (Step 4; strict JSON; no design policy by default)."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any, Awaitable, Callable, Optional

from pydantic import ValidationError

from adami_kernel.cortex.intent_adaptive.merge_policies import apply_family_merge_policy
from adami_kernel.cortex.intent_adaptive.models import (
    IntentClassificationResult,
    IntentFamily,
    IntentType,
    default_unknown_result,
)

logger = logging.getLogger("AdamI-IntentLLMClassifier")


def _allowed_families_csv() -> str:
    return ", ".join(m.value for m in IntentFamily)


def _allowed_primary_types_csv() -> str:
    """Known ``IntentType`` wire ids (English list for the prompt)."""
    out: set[str] = set()
    for val in vars(IntentType).values():
        if isinstance(val, str) and val:
            out.add(val)
    return ", ".join(sorted(out))


def build_intent_classification_llm_prompt(task_text: str) -> str:
    """English-only instruction block; model must emit JSON only."""
    families = _allowed_families_csv()
    types_csv = _allowed_primary_types_csv()
    body = (task_text or "").strip()[:4000]
    return (
        "You are a strict JSON emitter for AdamI intent classification.\n"
        "Return exactly one JSON object and nothing else (no markdown fences, no commentary).\n"
        "Schema keys: primary_family, primary_type, confidence, slots, route, reason_codes\n"
        "Optional (Step 4.1): families (JSON array of extra family wire strings), "
        "secondary_types (JSON array of extra intent-type wire ids).\n"
        "Merge policy if families is set: ``system`` beats any other label; ``action`` "
        "requires an explicit permission grant from the host — otherwise demote to "
        "``clarify`` or reject when action is the only label.\n"
        f"- primary_family: one of [{families}]\n"
        f"- primary_type: prefer one of [{types_csv}], or a new lowercase wire id such as "
        '"retrieval.custom".\n'
        "- confidence: number in [0, 1].\n"
        "- slots: flat object; keys must be snake_case ASCII.\n"
        '- route: one of "template", "dynamic", "clarify".\n'
        '- reason_codes: JSON array of short strings; include "llm_based".\n\n'
        "User task:\n---\n"
        f"{body}\n---\n"
        "JSON object:"
    )


def _extract_json_text(raw: str) -> str:
    text = (raw or "").strip()
    m = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
    if m:
        return m.group(1).strip()
    return text


def parse_llm_classification_json(raw: str) -> IntentClassificationResult:
    """Parse model output into ``IntentClassificationResult`` (raises on failure)."""
    blob = _extract_json_text(raw)
    data = json.loads(blob)
    if not isinstance(data, dict):
        raise ValueError("root must be a JSON object")
    return IntentClassificationResult.model_validate(data)


def _ensure_llm_reason_codes(result: IntentClassificationResult) -> IntentClassificationResult:
    codes = list(result.reason_codes or [])
    if "llm_based" not in codes:
        codes.append("llm_based")
    return result.model_copy(update={"reason_codes": codes})


async def maybe_llm_classify_after_rule(
    task_text: str,
    *,
    router_tag: str,
    router_data: Any,
    rule_result: Optional[IntentClassificationResult],
    call_llm: Callable[..., Awaitable[str]],
    enabled: bool,
    min_confidence: float,
    timeout_sec: float,
    action_permission_granted: bool = False,
) -> Optional[IntentClassificationResult]:
    """
    When ``enabled`` is False, returns ``rule_result`` unchanged (Step 3 parity).

    When ``enabled`` is True and ``router_tag`` is ``COMPLEX_TASK``, calls ``call_llm``
    only if the rule tier is absent, ``UNKNOWN`` family, or ``confidence < min_confidence``.
    Parse failures and timeouts downgrade to ``default_unknown_result`` with
    ``route="dynamic"`` and machine ``reason_codes``.
    """
    _ = router_data
    if not enabled:
        return rule_result
    if router_tag != "COMPLEX_TASK":
        return rule_result

    strong_rule = (
        rule_result is not None
        and rule_result.primary_family != IntentFamily.UNKNOWN
        and float(rule_result.confidence) >= float(min_confidence)
    )
    if strong_rule:
        return rule_result

    prompt = build_intent_classification_llm_prompt(task_text)

    async def _invoke() -> str:
        return await call_llm(
            prompt,
            brain_type="action",
            temperature=0.1,
            apply_design_output_policy=False,
            skip_design_output_policy=True,
        )

    try:
        raw = await asyncio.wait_for(_invoke(), timeout=float(timeout_sec))
        parsed = parse_llm_classification_json(raw)
        merged = apply_family_merge_policy(
            parsed, action_permission_granted=action_permission_granted
        )
        return _ensure_llm_reason_codes(merged)
    except asyncio.TimeoutError:
        logger.warning("[intent_llm_classifier] timeout after %.2fs", float(timeout_sec))
        return default_unknown_result(
            route="dynamic",
            reason_codes=["llm_classifier_timeout", "llm_classifier_unavailable"],
        )
    except (ValidationError, json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning("[intent_llm_classifier] parse failed: %s", e)
        return default_unknown_result(
            route="dynamic",
            reason_codes=["llm_classifier_parse_error"],
        )
    except Exception as e:
        logger.warning("[intent_llm_classifier] call failed: %s", e)
        return default_unknown_result(
            route="dynamic",
            reason_codes=["llm_classifier_unavailable"],
        )


async def maybe_llm_classify_with_settings(
    task_text: str,
    *,
    router_tag: str,
    router_data: Any,
    rule_result: Optional[IntentClassificationResult],
    call_llm: Callable[..., Awaitable[str]],
    settings: Optional[Any] = None,
) -> Optional[IntentClassificationResult]:
    """Reads ``ADAMI_INTENT_*`` fields from ``settings`` (defaults to ``config.settings``)."""
    from adami_kernel.config import settings as global_settings

    s = settings if settings is not None else global_settings
    return await maybe_llm_classify_after_rule(
        task_text,
        router_tag=router_tag,
        router_data=router_data,
        rule_result=rule_result,
        call_llm=call_llm,
        enabled=bool(getattr(s, "ADAMI_INTENT_LLM_CLASSIFIER_ENABLED", False)),
        min_confidence=float(getattr(s, "ADAMI_INTENT_CLASSIFIER_MIN_CONFIDENCE", 0.55)),
        timeout_sec=float(getattr(s, "ADAMI_INTENT_CLASSIFIER_TIMEOUT_SEC", 8.0)),
        action_permission_granted=bool(getattr(s, "ADAMI_INTENT_ACTION_PERMISSION_GRANTED", False)),
    )
