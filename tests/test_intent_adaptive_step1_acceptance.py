# tests/test_intent_adaptive_step1_acceptance.py
"""
Step 1 acceptance tests for ``adami_kernel.cortex.intent_adaptive`` (see
``docs/intent_adaptive_pipeline.md`` § Step 1 — Acceptance test plan).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from adami_kernel.cortex.intent_adaptive import (
    IntentClassificationResult,
    IntentFamily,
    IntentType,
    default_unknown_result,
)
from adami_kernel.cortex.intent_adaptive.models import IntentRoute

_REPO = Path(__file__).resolve().parents[1]
_README = _REPO / "README.md"
_LOCALES = _REPO / "src" / "adami_kernel" / "i18n" / "locales"


# --- A. Contract and packaging ---


def test_a1_package_import_and_all_exports() -> None:
    import adami_kernel.cortex.intent_adaptive as ia

    for name in ia.__all__:
        assert hasattr(ia, name), f"missing export: {name}"
    assert set(ia.__all__) >= {
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
        "TemplateExecutionContext",
        "TemplateOutcome",
        "TemplateRegistry",
        "build_intent_classification_llm_prompt",
        "default_unknown_result",
        "intent_span_attributes_dict",
        "maybe_llm_classify_after_rule",
        "maybe_llm_classify_with_settings",
        "parse_llm_classification_json",
        "record_intent_classification_on_span",
        "rule_classify_after_router",
        "apply_family_merge_policy",
    }


def test_a2_intent_family_distinct_wire_values() -> None:
    vals = [m.value for m in IntentFamily]
    assert len(vals) == len(set(vals))
    for v in vals:
        assert v == v.lower()
        assert v.isascii()


# --- B. Pydantic validation ---


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_b1_confidence_boundaries(confidence: float) -> None:
    r = IntentClassificationResult(
        primary_family=IntentFamily.CONVERSATION,
        primary_type="conversation.smalltalk",
        confidence=confidence,
        slots={},
        route="dynamic",
    )
    assert r.confidence == confidence


@pytest.mark.parametrize(
    ("kwargs", "needle"),
    [
        ({"confidence": 1.01}, "less_than_equal"),
        ({"confidence": -0.01}, "greater_than_equal"),
        ({"primary_type": ""}, "at least 1 character"),
        ({"route": "invalid_route"}, "route"),  # literal union
    ],
)
def test_b2_b3_reject_invalid_core_fields(kwargs: dict, needle: str) -> None:
    base = dict(
        primary_family=IntentFamily.UNKNOWN,
        primary_type=IntentType.UNKNOWN,
        confidence=0.5,
        slots={},
        route="dynamic",
    )
    base.update(kwargs)
    with pytest.raises(ValidationError) as exc:
        IntentClassificationResult(**base)
    err = str(exc.value).lower()
    assert needle.lower() in err


def test_b2_extra_fields_forbidden() -> None:
    with pytest.raises(ValidationError):
        IntentClassificationResult(
            primary_family=IntentFamily.UNKNOWN,
            primary_type=IntentType.UNKNOWN,
            confidence=0.5,
            slots={},
            route="dynamic",
            unexpected_field=True,  # type: ignore[call-arg]
        )


@pytest.mark.parametrize(
    "bad_slots",
    [
        {"BadKey": "x"},
        {"2bad": "x"},
        {"no-hyphen": "x"},
    ],
)
def test_b4_slots_key_snake_case_only(bad_slots: dict) -> None:
    with pytest.raises(ValidationError):
        IntentClassificationResult(
            primary_family=IntentFamily.RETRIEVAL,
            primary_type="retrieval.test",
            confidence=0.9,
            slots=bad_slots,
            route="template",
        )


def test_b4_slots_valid_nested_values_allowed() -> None:
    """Values may be structured; only keys are constrained."""
    r = IntentClassificationResult(
        primary_family=IntentFamily.SYNTHESIS,
        primary_type="synthesis.report",
        confidence=0.7,
        slots={"items": [{"a": 1}, {"b": 2}], "count": 2},
        route="template",
    )
    assert r.slots["count"] == 2


# --- C. Serialization ---


def test_c1_model_dump_round_trip() -> None:
    original = IntentClassificationResult(
        primary_family=IntentFamily.PLANNING,
        primary_type="planning.roadmap",
        confidence=0.42,
        slots={"horizon_days": "7", "goal": "ship mvp"},
        route="clarify",
        reason_codes=["llm_low_confidence", "slot_goal_ambiguous"],
        secondary_types=["planning.milestone"],
        family_candidates=[IntentFamily.SYNTHESIS],
    )
    payload = original.model_dump(mode="json")
    text = json.dumps(payload, ensure_ascii=False)
    restored = IntentClassificationResult.model_validate(json.loads(text))
    assert restored == original


# --- D. Factory ---


def test_d1_default_unknown_result() -> None:
    d = default_unknown_result()
    assert d.primary_family == IntentFamily.UNKNOWN
    assert d.primary_type == IntentType.UNKNOWN
    assert d.confidence == 0.0
    assert d.slots == {}
    assert d.route == "dynamic"
    assert d.reason_codes == ["default_unknown"]

    c = default_unknown_result(route="clarify", reason_codes=["manual"])
    assert c.route == "clarify"
    assert c.reason_codes == ["manual"]


# --- E. Repository hygiene ---


def test_e1_readme_links_design_doc() -> None:
    text = _README.read_text(encoding="utf-8")
    assert "intent_adaptive_pipeline.md" in text
    assert "cortex/intent_adaptive" in text
    assert "doc.intent_adaptive.step6_templates" in text
    low = text.lower()
    assert "template registry" in low or "templateregistry" in low.replace("`", "").replace("*", "")


@pytest.mark.parametrize("locale", ["en", "zh-Hans"])
@pytest.mark.parametrize(
    "key",
    [
        "doc.intent_adaptive.overview",
        "doc.intent_adaptive.step1_models",
        "doc.intent_adaptive.step2_template_registry",
        "doc.intent_adaptive.rule_tier",
        "doc.intent_adaptive.step4_llm_classifier",
        "doc.intent_adaptive.step41_merge",
        "doc.intent_adaptive.step5_decision_wiring",
        "doc.intent_adaptive.step6_templates",
        "doc.intent_adaptive.step51_observability",
        "doc.intent_adaptive.planner_hook",
        "doc.intent_adaptive.step8_guards",
        "doc.intent_adaptive.step81_hitl_action",
        "doc.intent_adaptive.ci",
        "doc.operator.intent_adaptive_grep",
        "intent.classifier.parse_error",
        "intent.classifier.unavailable",
        "intent.clarify.prompt",
        "intent.adaptive.user.fallback_to_planner",
        "intent.action_template.confirm_required",
        "intent.action_template.hitl_body",
        "intent.action_template.hitl_btn_confirm",
        "intent.action_template.hitl_btn_abort",
        "intent.action_template.hitl_toast_confirmed",
        "intent.action_template.hitl_toast_aborted",
        "intent.action_template.hitl_fallback_body",
        "intent.adaptive.template_execute_timeout",
        "intent.help.body",
        "intent.help.supported_types",
        "intent.template.weather_title",
        "intent.template.weather_stub",
        "intent.template.crypto_title",
        "intent.template.crypto_stub",
        "intent.template.no_match",
    ],
)
def test_e2_i18n_doc_keys_bilingual(locale: str, key: str) -> None:
    path = _LOCALES / locale / "common.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert key in data, f"missing {key} in {path}"
    assert str(data[key]).strip(), f"empty {key} in {path}"


def test_s9b1_doc_intent_adaptive_ci_locales_differ() -> None:
    """Step 9 (S9-B1): operator doc string differs per shipped locale."""
    en = json.loads((_LOCALES / "en" / "common.json").read_text(encoding="utf-8"))[
        "doc.intent_adaptive.ci"
    ]
    zh = json.loads((_LOCALES / "zh-Hans" / "common.json").read_text(encoding="utf-8"))[
        "doc.intent_adaptive.ci"
    ]
    assert str(en).strip() and str(zh).strip()
    assert en != zh


# --- IntentRoute typing (static surface for callers) ---


def test_intent_route_literal_exported() -> None:
    """``IntentRoute`` is re-exported from the package for type hints."""
    from adami_kernel.cortex import intent_adaptive as ia

    assert ia.IntentRoute is IntentRoute
