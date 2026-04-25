# tests/test_intent_adaptive_registry.py
"""Unit tests for ``TemplateRegistry`` and handler scoring (Step 2)."""

from __future__ import annotations

import asyncio

import pytest

from adami_kernel.cortex.intent_adaptive import (
    IntentClassificationResult,
    IntentFamily,
    TemplateExecutionContext,
    TemplateOutcome,
    TemplateRegistry,
)
from adami_kernel.cortex.intent_adaptive.template_registry import NoOpTemplateHandler


class _ScoringHandler:
    """Test double: fixed score when ``primary_type`` matches ``needle``."""

    def __init__(self, needle: str, score: float, *, tag: str = "") -> None:
        self._needle = needle
        self._score = score
        self._tag = tag or str(score)

    async def match_score(self, classification: IntentClassificationResult) -> float:
        if classification.primary_type == self._needle:
            return self._score
        return 0.0

    async def execute(self, context: TemplateExecutionContext) -> TemplateOutcome:
        return TemplateOutcome(
            reply_markdown=f"handled-by-{self._tag}",
            telemetry={"needle": self._needle},
            handoff_to_dynamic=False,
        )


def test_resolve_picks_highest_match_score() -> None:
    async def _run() -> None:
        reg = TemplateRegistry()
        reg.register("demo.low", _ScoringHandler("demo.target", 0.3))
        reg.register("demo.high", _ScoringHandler("demo.target", 0.9))

        classification = IntentClassificationResult(
            primary_family=IntentFamily.RETRIEVAL,
            primary_type="demo.target",
            confidence=0.99,
            slots={},
            route="template",
        )
        winner = await reg.resolve(classification)
        assert winner is not None
        out = await winner.execute(
            TemplateExecutionContext(
                task_text="ping",
                chat_id="cli",
                platform="cli",
                trace_id="t-1",
            )
        )
        assert out.reply_markdown == "handled-by-0.9"

    asyncio.run(_run())


def test_resolve_returns_none_when_no_positive_score() -> None:
    async def _run() -> None:
        reg = TemplateRegistry()
        reg.register("noop", NoOpTemplateHandler())
        reg.register("miss", _ScoringHandler("other", 0.5))

        classification = IntentClassificationResult(
            primary_family=IntentFamily.UNKNOWN,
            primary_type="unrelated",
            confidence=0.1,
            slots={},
            route="dynamic",
        )
        assert await reg.resolve(classification) is None

    asyncio.run(_run())


def test_resolve_tie_breaker_first_registered_wins() -> None:
    async def _run() -> None:
        reg = TemplateRegistry()
        reg.register("a", _ScoringHandler("x", 0.5, tag="first"))
        reg.register("b", _ScoringHandler("x", 0.5, tag="second"))

        classification = IntentClassificationResult(
            primary_family=IntentFamily.SYNTHESIS,
            primary_type="x",
            confidence=1.0,
            slots={},
            route="template",
        )
        winner = await reg.resolve(classification)
        assert winner is not None
        out = await winner.execute(
            TemplateExecutionContext(
                task_text="t",
                chat_id="c",
                platform="cli",
                trace_id="t-2",
            )
        )
        assert out.reply_markdown == "handled-by-first"

    asyncio.run(_run())


def test_register_rejects_empty_intent_type() -> None:
    reg = TemplateRegistry()
    with pytest.raises(ValueError):
        reg.register("  ", NoOpTemplateHandler())
