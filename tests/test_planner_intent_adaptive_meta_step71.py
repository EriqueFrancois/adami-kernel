# tests/test_planner_intent_adaptive_meta_step71.py
"""Step 7.1: Planner prompts include optional English ``Prior intent guess:`` line from meta."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from adami_kernel.cortex.intent_adaptive.handoff_meta import build_prior_intent_guess_english_line
from adami_kernel.orchestrator import planner_prompts as pp


def test_prior_intent_line_contains_expected_substrings() -> None:
    meta = {
        "handoff_kind": "intent_adaptive_planner_fallback",
        "handoff_reason": "no_template_or_below_min_confidence",
        "primary_family": "conversation",
        "primary_type": "conversation.greeting",
        "confidence": 0.6,
        "route": "dynamic",
        "reason_codes": ["rule_based"],
    }
    line = build_prior_intent_guess_english_line(meta)
    assert line.startswith("Prior intent guess:")
    assert "route=dynamic" in line
    assert "family=conversation" in line
    assert "type=conversation.greeting" in line
    assert "confidence=0.60" in line
    assert "prior_tier_handoff=no_template_or_below_min_confidence" in line


def test_generate_plan_prompt_template_with_meta_block() -> None:
    prior = "Prior intent guess: route=dynamic, family=unknown, type=unknown, confidence=0.50; prior_tier_handoff=test."
    block = prior.strip() + "\n\n"
    prompt = pp.GENERATE_PLAN_PROMPT.format(
        preamble="",
        intent_meta_block=block,
        tools_section="TOOLS_HERE",
        task="USER_TASK_ONLY",
    )
    assert "Prior intent guess:" in prompt
    assert "route=dynamic" in prompt
    assert "USER_TASK_ONLY" in prompt
    assert prompt.index("Prior intent guess:") < prompt.index("USER_TASK_ONLY")


def test_generate_plan_prompt_template_without_meta_omits_phrase() -> None:
    prompt = pp.GENERATE_PLAN_PROMPT.format(
        preamble="",
        intent_meta_block="",
        tools_section="TOOLS",
        task="TASK",
    )
    assert "Prior intent guess:" not in prompt


def test_anthropic_wrapper_includes_prior_intent_block() -> None:
    prior = "Prior intent guess: route=template, family=unknown, type=unknown, confidence=0.99; prior_tier_handoff=x."
    prompt = pp.ANTHROPIC_SKILL_WRAPPER.format(
        skill_name="SK",
        required_params="[]",
        prompt_template="TEMPLATE_BODY",
        intent_meta_block=prior + "\n\n",
        brain_block="",
        task="do thing",
    )
    assert "Prior intent guess:" in prompt
    assert prompt.index("Prior intent guess:") < prompt.index("User task:")


def test_planner_generate_plan_call_llm_includes_prior_line_when_set() -> None:
    pytest.importorskip("aiosqlite")
    from adami_kernel.orchestrator.planner import TaskPlanner

    captured: dict[str, str] = {}

    async def capture_llm(*, prompt: str, **kwargs: object) -> str:
        captured["prompt"] = prompt
        return '{"steps": [{"action": "WEB_SEARCH", "args": {"query": "x"}}]}'

    ev = MagicMock()
    ev.get_registered_tools_for_llm = MagicMock(return_value="")

    planner = TaskPlanner(
        router=MagicMock(call_llm=AsyncMock(side_effect=capture_llm)),
        evolution_engine=ev,
        bus=MagicMock(),
        sensitive_filter=MagicMock(),
    )
    prior = (
        "Prior intent guess: route=dynamic, family=retrieval, type=retrieval.weather, "
        "confidence=0.60; prior_tier_handoff=no_template_or_below_min_confidence."
    )

    async def _run() -> None:
        await planner._generate_plan("plain task", "", intent_meta_line=prior)

    asyncio.run(_run())
    p = captured["prompt"]
    assert "Prior intent guess:" in p
    assert "plain task" in p


def test_planner_generate_plan_without_prior_line_no_phrase() -> None:
    pytest.importorskip("aiosqlite")
    from adami_kernel.orchestrator.planner import TaskPlanner

    captured: dict[str, str] = {}

    async def capture_llm(*, prompt: str, **kwargs: object) -> str:
        captured["prompt"] = prompt
        return '{"steps": [{"action": "WEB_SEARCH", "args": {"query": "x"}}]}'

    ev = MagicMock()
    ev.get_registered_tools_for_llm = MagicMock(return_value="")

    planner = TaskPlanner(
        router=MagicMock(call_llm=AsyncMock(side_effect=capture_llm)),
        evolution_engine=ev,
        bus=MagicMock(),
        sensitive_filter=MagicMock(),
    )

    async def _run() -> None:
        await planner._generate_plan("only task", "")

    asyncio.run(_run())
    assert "Prior intent guess:" not in captured["prompt"]
