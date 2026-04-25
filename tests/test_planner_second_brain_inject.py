"""步骤 18：Planner 在 _generate_plan 等路径拼入第二大脑检索摘要。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from adami_kernel.orchestrator.planner import TaskPlanner


@pytest.mark.asyncio
async def test_generate_plan_prompt_contains_resources_preamble():
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

    preamble = "【第二大脑 · 与 Resources 等相关】\n### `Resources/x.md`\n"
    await planner._generate_plan("测试任务", brain_preamble=preamble)
    p = captured.get("prompt", "")
    assert "第二大脑" in p and "Resources" in p
    assert "测试任务" in captured["prompt"]
