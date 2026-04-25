# src/adami_kernel/cortex/intent_adaptive/__init__.py
"""Tiered intent classification and template routing (incremental rollout)."""

from adami_kernel.cortex.intent_adaptive.llm_classifier import (
    build_intent_classification_llm_prompt,
    maybe_llm_classify_after_rule,
    maybe_llm_classify_with_settings,
    parse_llm_classification_json,
)
from adami_kernel.cortex.intent_adaptive.merge_policies import apply_family_merge_policy
from adami_kernel.cortex.intent_adaptive.models import (
    IntentClassificationResult,
    IntentFamily,
    IntentRoute,
    IntentType,
    default_unknown_result,
)
from adami_kernel.cortex.intent_adaptive.outcomes import TemplateOutcome
from adami_kernel.cortex.intent_adaptive.rule_classifier import (
    RULE_CONFIDENCE_MAX,
    rule_classify_after_router,
)
from adami_kernel.cortex.intent_adaptive.telemetry import (
    ATTR_INTENT_CONFIDENCE,
    ATTR_INTENT_FAMILY,
    ATTR_INTENT_ROUTE,
    ATTR_INTENT_TYPE,
    intent_span_attributes_dict,
    record_intent_classification_on_span,
)
from adami_kernel.cortex.intent_adaptive.template_registry import (
    IntentTemplateHandler,
    NoOpTemplateHandler,
    TemplateExecutionContext,
    TemplateRegistry,
)

__all__ = [
    "ATTR_INTENT_CONFIDENCE",
    "ATTR_INTENT_FAMILY",
    "ATTR_INTENT_ROUTE",
    "ATTR_INTENT_TYPE",
    "IntentClassificationResult",
    "IntentFamily",
    "IntentRoute",
    "IntentTemplateHandler",
    "IntentType",
    "NoOpTemplateHandler",
    "RULE_CONFIDENCE_MAX",
    "apply_family_merge_policy",
    "build_intent_classification_llm_prompt",
    "TemplateExecutionContext",
    "TemplateOutcome",
    "TemplateRegistry",
    "default_unknown_result",
    "intent_span_attributes_dict",
    "maybe_llm_classify_after_rule",
    "maybe_llm_classify_with_settings",
    "parse_llm_classification_json",
    "record_intent_classification_on_span",
    "rule_classify_after_router",
]
