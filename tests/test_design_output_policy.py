"""Design-output policy injection (awesome-design-systems–aligned)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from adami_kernel.config import settings
from adami_kernel.cortex import design_output_policy as dop
from adami_kernel.cortex.router import HybridLLMRouter


def test_load_policy_contains_markdown_guidance() -> None:
    dop.invalidate_design_output_policy_cache()
    text = dop.load_design_output_policy_text(max_chars=6000)
    assert "Markdown" in text or "markdown" in text
    assert "awesome-design-systems" in text or "alexpate" in text


def test_prefix_wraps_user_prompt() -> None:
    dop.invalidate_design_output_policy_cache()
    out = dop.prefix_prompt_with_design_policy("HELLO_USER_MARKER")
    assert "HELLO_USER_MARKER" in out
    assert "<DESIGN_OUTPUT_POLICY" in out


def test_disabled_returns_empty_prefix(monkeypatch: pytest.MonkeyPatch) -> None:
    dop.invalidate_design_output_policy_cache()
    monkeypatch.setattr(settings, "ADAMI_DESIGN_OUTPUT_POLICY_ENABLED", False)
    assert dop.load_design_output_policy_text() == ""
    assert dop.prefix_prompt_with_design_policy("X") == "X"


@pytest.mark.asyncio
async def test_call_llm_prefix_only_when_apply_design_output_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dop.invalidate_design_output_policy_cache()
    monkeypatch.setattr(settings, "ADAMI_DESIGN_OUTPUT_POLICY_ENABLED", True)
    # Replay/sim tests may leave these True; the offline stub never hits _call_openai_format.
    monkeypatch.setattr(settings, "ADAMI_SIM_OFFLINE", False)
    monkeypatch.setattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False)

    prompts: list[str] = []

    async def fake_openai(self, provider, prompt, **kwargs):
        prompts.append(prompt)
        return "ok"

    monkeypatch.setattr(HybridLLMRouter, "_call_openai_format", fake_openai)
    monkeypatch.setattr("adami_kernel.cortex.router.get_experience_sink", lambda: MagicMock())

    r = object.__new__(HybridLLMRouter)
    r.think_providers = []
    r.action_providers = [
        {
            "name": "stub",
            "api_key": "x",
            "model": "m",
            "base_url": "https://example.invalid/v1",
        }
    ]
    r.current_think_idx = 0
    r.current_action_idx = 0
    r.think_failure_count = {"stub": 0}
    r.action_failure_count = {"stub": 0}
    r.last_call_time = 0.0

    marker = "USER_PROMPT_MARKER_PLAIN"
    await r.call_llm(marker, brain_type="action")
    assert prompts[-1] == marker
    assert "<DESIGN_OUTPUT_POLICY" not in prompts[-1]

    prompts.clear()
    await r.call_llm(marker, brain_type="action", apply_design_output_policy=True)
    assert "<DESIGN_OUTPUT_POLICY" in prompts[-1]
    assert marker in prompts[-1]

    prompts.clear()
    await r.call_llm(
        marker,
        brain_type="action",
        apply_design_output_policy=True,
        skip_design_output_policy=True,
    )
    assert prompts[-1] == marker
