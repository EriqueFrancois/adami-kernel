# src/adami_kernel/cortex/intent_adaptive/handoff_meta.py
"""Step 7 / 7.1: ``intent_adaptive_meta`` for Planner handoff and optional prompt hints."""

from __future__ import annotations

from typing import Any, Dict, Optional

from adami_kernel.cortex.intent_adaptive.models import IntentClassificationResult, IntentFamily


def build_planner_handoff_meta(
    classification: Optional[IntentClassificationResult],
    *,
    handoff_reason: str,
) -> Dict[str, Any]:
    """
    English-key payload for ``TaskPlanner.plan_and_execute(..., intent_adaptive_meta=...)``.
    Safe for JSON logging; Step 7.1 uses :func:`build_prior_intent_guess_english_line` for prompts.
    """
    meta: Dict[str, Any] = {
        "handoff_kind": "intent_adaptive_planner_fallback",
        "handoff_reason": str(handoff_reason),
    }
    if classification is not None:
        fam = classification.primary_family
        meta["primary_family"] = fam.value if hasattr(fam, "value") else str(fam)
        meta["primary_type"] = str(classification.primary_type)
        meta["confidence"] = float(classification.confidence)
        meta["route"] = str(classification.route)
        meta["reason_codes"] = list(classification.reason_codes or [])
        if (
            str(classification.route) == "dynamic"
            or classification.primary_family == IntentFamily.UNKNOWN
        ):
            meta["dynamic_or_unknown_tail"] = True
    return meta


def handoff_reason_for_planner_fallback(
    classification: IntentClassificationResult,
    *,
    handler: Any,
    min_confidence: float,
    template_handoff_to_planner: bool,
    empty_template_body: bool = False,
) -> str:
    """Machine-readable reason for the downgrade path (logging + meta)."""
    if template_handoff_to_planner:
        return "template_handoff_to_planner"
    if empty_template_body:
        return "empty_template_body_planner"
    if handler is None or float(classification.confidence) < float(min_confidence):
        if str(classification.route) == "clarify":
            return "clarify_below_min_confidence_or_no_template"
        return "no_template_or_below_min_confidence"
    return "planner_fallback_other"


def build_prior_intent_guess_english_line(meta: Dict[str, Any], *, max_len: int = 500) -> str:
    """
    One English line for Planner LLM prompts (Step 7.1), prefixed with ``Prior intent guess:``.
    """
    if not meta:
        return ""
    route = meta.get("route", "?")
    fam = meta.get("primary_family", "?")
    typ = meta.get("primary_type", "?")
    conf = meta.get("confidence")
    if isinstance(conf, (int, float)):
        conf_s = f"{float(conf):.2f}"
    else:
        conf_s = str(conf)
    reason = meta.get("handoff_reason", "?")
    line = (
        f"Prior intent guess: route={route}, family={fam}, type={typ}, "
        f"confidence={conf_s}; prior_tier_handoff={reason}."
    )
    if len(line) > max_len:
        return line[: max_len - 1] + "…"
    return line
