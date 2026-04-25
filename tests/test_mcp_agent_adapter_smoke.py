"""步骤 6 — mcp-agent 适配器与步骤 4 试点路径回归（mock LLM/MCP，无 Docker）。

- **无 ``mcp_agent`` 包**：整模块 ``pytest.importorskip`` → CI 默认 ``poetry install`` 下 **skip**（绿）。
- **``poetry install -E mcp-agent``**：本文件用 mock 跑全量，不拉真实 LLM/Docker。

可选：将来可加 ``@pytest.mark.docker`` 的真容器用例，由单独 job 执行 ``-m docker``。
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator
from unittest.mock import AsyncMock, MagicMock

import pytest

pytest.importorskip("mcp_agent")


class _FakeTextBlock:
    type = "text"

    def __init__(self, text: str) -> None:
        self.text = text


class _FakeCallToolResult:
    def __init__(self, text: str) -> None:
        self.content = [_FakeTextBlock(text)]
        self.isError = False
        self.structuredContent = None


@pytest.mark.asyncio
async def test_smoke_try_execute_via_mcp_agent_mocked_runtime_and_agent(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock ``adamimcp_runtime`` + ``Agent.call_tool``，验证 tool_executor 文本收口。"""
    import mcp_agent.agents.agent as mcp_agent_agent_mod

    import adami_kernel.integration.mcp_agent.adapter as adapter_mod
    from adami_kernel.integration.mcp_agent import tool_executor as te
    from adami_kernel.integration.mcp_agent.contracts import ToolInvocation, tool_capability_mcp

    monkeypatch.setattr("adami_kernel.config.settings.ADAMI_USE_MCP_AGENT", True)

    @asynccontextmanager
    async def _mock_runtime(*, app_name: str = "") -> AsyncIterator[tuple[MagicMock, list[str]]]:
        ra = MagicMock()
        ra.context = MagicMock()
        yield ra, ["testsrv"]

    monkeypatch.setattr(adapter_mod, "adamimcp_runtime", _mock_runtime)

    class _MockAgent:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "_MockAgent":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def call_tool(
            self,
            name: str,
            arguments: dict | None,
            server_name: str | None = None,
        ) -> _FakeCallToolResult:
            assert name == "echo"
            assert server_name == "testsrv"
            return _FakeCallToolResult("mocked-mcp-result")

    monkeypatch.setattr(mcp_agent_agent_mod, "Agent", _MockAgent)

    cap = tool_capability_mcp(
        "MCP.TESTSRV.ECHO",
        {"type": "object", "properties": {}},
        "echo tool",
        "testsrv",
        "echo",
    )
    inv = ToolInvocation(
        tool_id="MCP.TESTSRV.ECHO",
        args={"msg": "hi"},
        trace_id="smoke_t1",
        chat_id="c1",
    )
    out = await te.try_execute_via_mcp_agent(inv, cap)
    assert out == "mocked-mcp-result"


@pytest.mark.asyncio
async def test_smoke_run_single_turn_mock_llm_no_openai_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mock ``adamimcp_runtime`` + ``Agent.attach_llm.generate_str``，不触网、不建 MCPApp。"""
    import mcp_agent.agents.agent as mcp_agent_agent_mod

    import adami_kernel.integration.mcp_agent.adapter as adapter_mod
    from adami_kernel.integration.mcp_agent.adapter import run_single_turn_with_agent_llm

    @asynccontextmanager
    async def _mock_runtime(*, app_name: str = "") -> AsyncIterator[tuple[MagicMock, list[str]]]:
        ra = MagicMock()
        ra.context = MagicMock()
        yield ra, ["srv_a"]

    monkeypatch.setattr(adapter_mod, "adamimcp_runtime", _mock_runtime)

    class _MockAgent:
        def __init__(self, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "_MockAgent":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def attach_llm(self, llm_factory: object = None) -> MagicMock:
            llm = MagicMock()
            llm.generate_str = AsyncMock(return_value="mock_generate_str_ok")
            return llm

    monkeypatch.setattr(mcp_agent_agent_mod, "Agent", _MockAgent)

    text = await run_single_turn_with_agent_llm("ping", llm_mode="openai")
    assert text == "mock_generate_str_ok"


@pytest.mark.asyncio
async def test_smoke_step4_execute_tool_dispatch_prefers_mcp_agent_pilot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """步骤 4：``ADAMI_USE_MCP_AGENT`` + pilot 返回非空时不再走 Docker ``get_skill``。"""
    monkeypatch.setattr("adami_kernel.config.settings.ADAMI_USE_MCP_AGENT", True)
    from adami_kernel.cortex.evolution import EvolutionEngine

    ee = EvolutionEngine(toolbox=None)

    async def _docker_should_not_run(**_kwargs: object) -> str:
        raise AssertionError("Docker/native skill path should not run when pilot succeeds")

    ee.dynamic_skills["MCP.SMOKE.STEP4"] = _docker_should_not_run
    ee.register_tool(
        "MCP.SMOKE.STEP4",
        {"type": "object", "properties": {}},
        "smoke",
        tool_source="mcp",
        mcp_server="srv",
        mcp_tool_name="echo",
    )

    async def _fake_pilot(inv, cap) -> str:  # noqa: ANN001
        assert inv.trace_id == "step4_trace"
        assert cap.mcp_tool_name == "echo"
        return "from_mcp_agent_pilot"

    monkeypatch.setattr(
        "adami_kernel.integration.mcp_agent.tool_executor.try_execute_via_mcp_agent",
        _fake_pilot,
    )

    out = await ee.execute_tool_dispatch(
        "MCP.SMOKE.STEP4",
        {"x": 1},
        trace_id="step4_trace",
        chat_id="step4_chat",
    )
    assert out == "from_mcp_agent_pilot"
