# tests/test_intent_adaptive_step41_acceptance.py
"""
Step 4.1 acceptance tests (see ``docs/intent_adaptive_pipeline.md`` § Step 4.1 — Acceptance test plan).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

import adami_kernel.cortex.intent_adaptive as ia
from adami_kernel.config import settings
from adami_kernel.cortex.intent_adaptive import (
    IntentClassificationResult,
    IntentFamily,
    maybe_llm_classify_after_rule,
    parse_llm_classification_json,
)
from adami_kernel.i18n.catalog import default_translator

_REPO = Path(__file__).resolve().parents[1]
_README = _REPO / "README.md"
_LOCALES = _REPO / "src" / "adami_kernel" / "i18n" / "locales"


def test_s41a_export_merge_policy() -> None:
    assert "apply_family_merge_policy" in ia.__all__
    assert callable(ia.apply_family_merge_policy)


def test_s41b_families_alias_maps_to_family_candidates() -> None:
    raw = json.dumps(
        {
            "primary_family": "planning",
            "primary_type": "planning.goal",
            "confidence": 0.5,
            "slots": {},
            "route": "dynamic",
            "reason_codes": [],
            "families": ["synthesis"],
            "secondary_types": ["synthesis.summary"],
        }
    )
    r = parse_llm_classification_json(raw)
    assert r.family_candidates == [IntentFamily.SYNTHESIS]
    assert r.secondary_types == ["synthesis.summary"]


def test_s41b_invalid_secondary_type() -> None:
    with pytest.raises(ValidationError):
        IntentClassificationResult(
            primary_family=IntentFamily.UNKNOWN,
            primary_type="unknown",
            confidence=0.1,
            slots={},
            route="dynamic",
            secondary_types=["BadCaps"],
        )


def test_s41d_model_dump_round_trip_preserves_new_fields() -> None:
    r = IntentClassificationResult(
        primary_family=IntentFamily.RETRIEVAL,
        primary_type="retrieval.test",
        confidence=0.33,
        slots={"q": "x"},
        route="dynamic",
        reason_codes=["t"],
        secondary_types=["retrieval.crypto"],
        family_candidates=[IntentFamily.SYNTHESIS],
    )
    blob = r.model_dump(mode="json")
    text = json.dumps(blob, ensure_ascii=False)
    restored = IntentClassificationResult.model_validate(json.loads(text))
    assert restored.secondary_types == ["retrieval.crypto"]
    assert restored.family_candidates == [IntentFamily.SYNTHESIS]


def test_s41e_action_permission_default_false() -> None:
    assert settings.ADAMI_INTENT_ACTION_PERMISSION_GRANTED is False


def test_s41f_llm_path_applies_merge_on_success() -> None:
    payload = json.dumps(
        {
            "primary_family": "synthesis",
            "primary_type": "synthesis.summary",
            "confidence": 0.9,
            "slots": {},
            "route": "dynamic",
            "reason_codes": ["llm_based"],
            "families": ["system"],
        }
    )
    call_llm = AsyncMock(return_value=payload)
    out = asyncio.run(
        maybe_llm_classify_after_rule(
            "multi intent probe",
            router_tag="COMPLEX_TASK",
            router_data=None,
            rule_result=None,
            call_llm=call_llm,
            enabled=True,
            min_confidence=0.55,
            timeout_sec=5.0,
            action_permission_granted=False,
        )
    )
    assert out is not None
    assert out.primary_family == IntentFamily.SYSTEM
    assert "merge_family_system_wins" in out.reason_codes
    assert "llm_based" in out.reason_codes


@pytest.mark.parametrize("locale", ["en", "zh-Hans"])
@pytest.mark.parametrize(
    "key",
    ["intent.clarify.prompt", "doc.intent_adaptive.step41_merge"],
)
def test_s41g_i18n_keys_present(locale: str, key: str) -> None:
    path = _LOCALES / locale / "common.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    assert key in data and str(data[key]).strip()


def test_s41g_bilingual_doc_differs() -> None:
    tr = default_translator()
    a = tr.t("doc.intent_adaptive.step41_merge", locale="en")
    b = tr.t("doc.intent_adaptive.step41_merge", locale="zh-Hans")
    assert a != b


def test_s41g_clarify_prompt_differs_by_locale() -> None:
    tr = default_translator()
    a = tr.t("intent.clarify.prompt", locale="en")
    b = tr.t("intent.clarify.prompt", locale="zh-Hans")
    assert a != b


def test_s41h_readme_mentions_step41_merge_signals() -> None:
    text = _README.read_text(encoding="utf-8")
    assert "doc.intent_adaptive.step41_merge" in text or "merge" in text.lower()
    assert "ADAMI_INTENT_ACTION_PERMISSION_GRANTED" in text
