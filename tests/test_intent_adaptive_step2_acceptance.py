# tests/test_intent_adaptive_step2_acceptance.py
"""
Step 2 acceptance tests for ``intent_adaptive`` template registry (see
``docs/intent_adaptive_pipeline.md`` § Step 2 — Acceptance test plan).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

import adami_kernel.cortex.intent_adaptive as ia
from adami_kernel.cortex.intent_adaptive import (
    IntentClassificationResult,
    IntentFamily,
    TemplateExecutionContext,
    TemplateOutcome,
    TemplateRegistry,
)
from adami_kernel.cortex.intent_adaptive.template_registry import NoOpTemplateHandler

_REPO = Path(__file__).resolve().parents[1]
_README = _REPO / "README.md"
_LOCALES = _REPO / "src" / "adami_kernel" / "i18n" / "locales"


# --- S2-A: Package surface ---


def test_s2a_package_exports_step2_symbols() -> None:
    required = {
        "IntentTemplateHandler",
        "NoOpTemplateHandler",
        "TemplateExecutionContext",
        "TemplateOutcome",
        "TemplateRegistry",
    }
    assert required <= set(ia.__all__)
    for name in required:
        assert hasattr(ia, name), name


# --- S2-B: TemplateOutcome ---


def test_s2b_template_outcome_defaults() -> None:
    o = TemplateOutcome()
    assert o.reply_markdown == ""
    assert o.telemetry == {}
    assert o.handoff_to_dynamic is False


# --- S2-C: TemplateExecutionContext ---


def test_s2c_execution_context_required_fields() -> None:
    ctx = TemplateExecutionContext(
        task_text="hello",
        chat_id="cli",
        platform="cli",
        trace_id="trace-99",
    )
    assert ctx.send_reply is None
    assert ctx.router_call_llm is None
    assert ctx.web_search is None
    assert ctx.classification is None


# --- S2-D: TemplateRegistry.min_match_score ---


def test_s2d_min_match_score_excludes_marginally_low_scores() -> None:
    class _FixedLow:
        async def match_score(self, classification: IntentClassificationResult) -> float:
            return 0.65

        async def execute(self, context: TemplateExecutionContext) -> TemplateOutcome:
            return TemplateOutcome()

    class _FixedHigh:
        async def match_score(self, classification: IntentClassificationResult) -> float:
            return 0.71

        async def execute(self, context: TemplateExecutionContext) -> TemplateOutcome:
            return TemplateOutcome(reply_markdown="ok")

    async def _run() -> None:
        c = IntentClassificationResult(
            primary_family=IntentFamily.UNKNOWN,
            primary_type="t",
            confidence=1.0,
            slots={},
            route="dynamic",
        )
        reg = TemplateRegistry(min_match_score=0.7)
        reg.register("x", _FixedLow())
        assert await reg.resolve(c) is None

        reg2 = TemplateRegistry(min_match_score=0.7)
        reg2.register("x", _FixedHigh())
        assert await reg2.resolve(c) is not None

    asyncio.run(_run())


# --- S2-E: register() normalizes intent_type ---


def test_s2e_register_strips_intent_type() -> None:
    reg = TemplateRegistry()
    reg.register("  demo.type  ", NoOpTemplateHandler())
    pairs = reg.registered_pairs()
    assert len(pairs) == 1
    assert pairs[0][0] == "demo.type"


# --- S2-F: NoOpTemplateHandler ---


def test_s2f_no_op_handler_execute() -> None:
    async def _run() -> None:
        h = NoOpTemplateHandler()
        ctx = TemplateExecutionContext(
            task_text="x",
            chat_id="c",
            platform="cli",
            trace_id="tid-1",
        )
        out = await h.execute(ctx)
        assert out.handoff_to_dynamic is True
        assert out.telemetry.get("intent_template") == "no_op"
        assert out.telemetry.get("trace_id") == "tid-1"
        assert (
            await h.match_score(
                IntentClassificationResult(
                    primary_family=IntentFamily.UNKNOWN,
                    primary_type="any",
                    confidence=1.0,
                    slots={},
                    route="dynamic",
                )
            )
            == 0.0
        )

    asyncio.run(_run())


# --- S2-G: registered_pairs snapshot ---


def test_s2g_registered_pairs_is_tuple_copy() -> None:
    reg = TemplateRegistry()
    reg.register("a", NoOpTemplateHandler())
    p1 = reg.registered_pairs()
    reg.register("b", NoOpTemplateHandler())
    p2 = reg.registered_pairs()
    assert len(p1) == 1
    assert len(p2) == 2


# --- S2-H: Repository hygiene (Step 2 i18n + README) ---


def test_s2h_readme_mentions_step2_and_registry() -> None:
    text = _README.read_text(encoding="utf-8")
    assert "Step 2" in text or "step 2" in text.lower()
    assert "TemplateRegistry" in text
    assert "doc.intent_adaptive.step2_template_registry" in text
    assert (
        "rule_classify_after_router" in text
        or "Phase 1" in text
        or "ADAMI_INTENT_LLM_CLASSIFIER_ENABLED" in text
    )


@pytest.mark.parametrize("locale", ["en", "zh-Hans"])
def test_s2h_i18n_step2_and_no_match_strings(locale: str) -> None:
    path = _LOCALES / locale / "common.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    for key in (
        "doc.intent_adaptive.step2_template_registry",
        "intent.template.no_match",
    ):
        assert key in data, key
        assert str(data[key]).strip(), f"empty {key} in {locale}"


def test_s2h_bilingual_doc_strings_differ() -> None:
    from adami_kernel.i18n.catalog import default_translator

    tr = default_translator()
    a = tr.t("doc.intent_adaptive.step2_template_registry", locale="en")
    b = tr.t("doc.intent_adaptive.step2_template_registry", locale="zh-Hans")
    assert a != b
