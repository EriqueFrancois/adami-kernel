from __future__ import annotations

import asyncio

import pytest

import adami_kernel.config as config_mod
from adami_kernel.integration.mcp_agent.contracts import ToolContractRegistry
from adami_kernel.mcp.manager import McpManager


class _FakeToolbox:
    def __init__(self) -> None:
        self.unregistered = 0

    def unregister_external_tools(self, *, source_prefix: str) -> int:
        assert source_prefix == "mcp:"
        self.unregistered += 1
        return 0


class _FakeEvolution:
    def __init__(self) -> None:
        self.tool_schemas = {}
        self.dynamic_skills = {}
        self.toolbox = _FakeToolbox()
        self.tool_contract_registry = ToolContractRegistry()

    def register_tool(
        self, name: str, json_schema: dict, description: str = "", **kwargs: object
    ) -> None:
        self.tool_schemas[str(name).upper()] = {
            "json_schema": json_schema,
            "description": description,
        }


def test_refresh_when_disabled_does_not_raise(monkeypatch: pytest.MonkeyPatch) -> None:
    evo = _FakeEvolution()
    mgr = McpManager(evolution_engine=evo)
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_ENABLED", False)

    async def run() -> None:
        await mgr.refresh()
        assert evo.toolbox.unregistered >= 1

    asyncio.run(run())
