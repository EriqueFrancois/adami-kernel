"""Tests for optional SecondBrain doc-pipeline hints in PromptBuilder.build_action_prompt."""

from __future__ import annotations

import pytest

from adami_kernel.config import settings
from adami_kernel.cortex.prompt import PromptBuilder


class _FakeSecondBrain:
    """Minimal SecondBrain surface for PromptBuilder injection tests."""

    def read_identity_context(self) -> str:
        return ""

    def read_second_brain_doctrine(self) -> str:
        return ""


@pytest.mark.asyncio
async def test_knowledge_wiki_hint_appended_when_flag_and_second_brain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ADAMI_PROMPT_KNOWLEDGE_WIKI_HINT", True)
    pb = PromptBuilder(
        system_persona="BASE",
        second_brain=_FakeSecondBrain(),
        policy_loader=None,
    )
    out = await pb.build_action_prompt({"task": "ping"}, [], "")
    assert "retrieve_brain_snippets" in out
    assert "/report run daily" in out


@pytest.mark.asyncio
async def test_knowledge_wiki_hint_skipped_without_second_brain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ADAMI_PROMPT_KNOWLEDGE_WIKI_HINT", True)
    monkeypatch.setattr(settings, "ADAMI_PROMPT_OUTPUT_EXAMPLES_REPORT_HINT", True)
    pb = PromptBuilder(system_persona="BASE", second_brain=None, policy_loader=None)
    out = await pb.build_action_prompt({"task": "ping"}, [], "")
    assert "retrieve_brain_snippets" not in out
    assert "/report run daily" not in out


@pytest.mark.asyncio
async def test_knowledge_wiki_hint_skipped_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ADAMI_PROMPT_KNOWLEDGE_WIKI_HINT", False)
    monkeypatch.setattr(settings, "ADAMI_PROMPT_OUTPUT_EXAMPLES_REPORT_HINT", False)
    pb = PromptBuilder(
        system_persona="BASE",
        second_brain=_FakeSecondBrain(),
        policy_loader=None,
    )
    out = await pb.build_action_prompt({"task": "ping"}, [], "")
    assert "retrieve_brain_snippets" not in out
    assert "/report run daily" not in out


@pytest.mark.asyncio
async def test_output_examples_report_hint_skipped_when_flag_off(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ADAMI_PROMPT_KNOWLEDGE_WIKI_HINT", True)
    monkeypatch.setattr(settings, "ADAMI_PROMPT_OUTPUT_EXAMPLES_REPORT_HINT", False)
    pb = PromptBuilder(
        system_persona="BASE",
        second_brain=_FakeSecondBrain(),
        policy_loader=None,
    )
    out = await pb.build_action_prompt({"task": "ping"}, [], "")
    assert "retrieve_brain_snippets" in out
    assert "/report run daily" not in out
