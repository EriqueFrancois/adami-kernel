"""TaskPlanner / EvolutionEngine 工具分发：契约层 + ADAMI_USE_MCP_AGENT 试点。"""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_execute_tool_dispatch_native_skips_mcp_pilot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("adami_kernel.config.settings.ADAMI_USE_MCP_AGENT", False)
    from adami_kernel.cortex.evolution import EvolutionEngine

    ee = EvolutionEngine(toolbox=None)

    async def skill(**kwargs: object) -> dict:
        return {"status": "success", "data": kwargs}

    ee.dynamic_skills["DEMO"] = skill
    ee.register_tool("DEMO", {"type": "object", "properties": {}}, "demo tool")
    out = await ee.execute_tool_dispatch("DEMO", {"x": 1}, trace_id="t1", chat_id="c1")
    assert out == {"status": "success", "data": {"x": 1}}


@pytest.mark.asyncio
async def test_execute_tool_dispatch_mcp_uses_pilot_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("adami_kernel.config.settings.ADAMI_USE_MCP_AGENT", True)
    from adami_kernel.cortex.evolution import EvolutionEngine

    ee = EvolutionEngine(toolbox=None)

    async def docker_skill(**_kwargs: object) -> str:
        return "docker"

    ee.dynamic_skills["MCP.SRV.ECHO"] = docker_skill
    ee.register_tool(
        "MCP.SRV.ECHO",
        {"type": "object", "properties": {}},
        "echo",
        tool_source="mcp",
        mcp_server="srv",
        mcp_tool_name="echo",
    )

    async def fake_try(inv, cap) -> str:  # noqa: ANN001
        assert inv.trace_id == "tid"
        assert cap.mcp_tool_name == "echo"
        return "from_mcp_agent"

    monkeypatch.setattr(
        "adami_kernel.integration.mcp_agent.tool_executor.try_execute_via_mcp_agent",
        fake_try,
    )
    out = await ee.execute_tool_dispatch(
        "MCP.SRV.ECHO", {"msg": "hi"}, trace_id="tid", chat_id="cid"
    )
    assert out == "from_mcp_agent"


@pytest.mark.asyncio
async def test_execute_tool_dispatch_mcp_pilot_none_falls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("adami_kernel.config.settings.ADAMI_USE_MCP_AGENT", True)
    from adami_kernel.cortex.evolution import EvolutionEngine

    ee = EvolutionEngine(toolbox=None)

    async def docker_skill(**kwargs: object) -> str:
        return f"docker:{kwargs.get('msg')}"

    ee.dynamic_skills["MCP.SRV.ECHO"] = docker_skill
    ee.register_tool(
        "MCP.SRV.ECHO",
        {"type": "object", "properties": {}},
        "echo",
        tool_source="mcp",
        mcp_server="srv",
        mcp_tool_name="echo",
    )

    async def fake_try(_inv, _cap) -> None:  # noqa: ANN001
        return None

    monkeypatch.setattr(
        "adami_kernel.integration.mcp_agent.tool_executor.try_execute_via_mcp_agent",
        fake_try,
    )
    out = await ee.execute_tool_dispatch("MCP.SRV.ECHO", {"msg": "x"}, trace_id="t2", chat_id="c2")
    assert out == "docker:x"


@pytest.mark.asyncio
async def test_execute_with_retry_passes_trace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("adami_kernel.config.settings.ADAMI_USE_MCP_AGENT", False)
    from adami_kernel.cortex.evolution import EvolutionEngine

    ee = EvolutionEngine(toolbox=None)

    async def _z(**_k: object) -> str:
        return "z"

    ee.dynamic_skills["Z"] = _z
    ee.register_tool("Z", {"type": "object", "properties": {}}, "z")
    out = await ee.execute_with_retry("Z", {}, trace_id="tr", chat_id="ch", max_retries=1)
    assert out == "z"
