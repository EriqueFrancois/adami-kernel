from __future__ import annotations

import asyncio

import pytest

import adami_kernel.config as config_mod
from adami_kernel.integration.mcp_agent.contracts import ToolContractRegistry
from adami_kernel.mcp.manager import McpManager
from adami_kernel.mcp.spec import McpServerSpec


class _FakeToolbox:
    def __init__(self) -> None:
        self.external = {}

    def register_external_tools(
        self, source: str, tools: list[dict], executors: dict, **kwargs: object
    ) -> None:
        for t in tools:
            self.external[str(t["name"]).upper()] = {"source": source}

    def unregister_external_tools(self, *, source_prefix: str) -> int:
        to_del = [
            k
            for k, v in self.external.items()
            if str(v.get("source", "")).startswith(source_prefix)
        ]
        for k in to_del:
            self.external.pop(k, None)
        return len(to_del)


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


def test_background_reload_updates_tools(monkeypatch: pytest.MonkeyPatch) -> None:
    async def run() -> None:
        evo = _FakeEvolution()
        mgr = McpManager(evolution_engine=evo)

        # 固定一个 server spec
        monkeypatch.setattr(
            "adami_kernel.mcp.manager.load_mcp_server_specs",
            lambda: [McpServerSpec(name="dummy", image="x", command=["python"])],
        )

        async def fake_regs(_runner, spec):
            # allow 为空 -> 不暴露；allow 含 echo -> 暴露一个工具
            allow = config_mod.settings.ADAMI_MCP_ALLOW_TOOLS or []
            if not allow:
                return []
            return [("MCP.DUMMY.ECHO", {"type": "object"}, "[MCP:dummy] echo", "echo")]

        monkeypatch.setattr("adami_kernel.mcp.manager.build_adami_tool_registrations", fake_regs)

        # 初始：enabled=true 但 allow 空 => 0 tools
        monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_ENABLED", True)
        monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_ALLOW_TOOLS", [])
        monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_DENY_TOOLS", [])
        await mgr.refresh()
        assert "MCP.DUMMY.ECHO" not in evo.tool_schemas

        # 启动后台任务
        task = asyncio.create_task(mgr.run_background(poll_sec=0.05))

        # 修改 allow，模拟 reload_settings() 后 settings 变化
        monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_ALLOW_TOOLS", ["echo"])

        # 等待后台检测到变化并 refresh
        for _ in range(50):
            if "MCP.DUMMY.ECHO" in evo.tool_schemas:
                break
            await asyncio.sleep(0.05)
        assert "MCP.DUMMY.ECHO" in evo.tool_schemas
        assert "MCP.DUMMY.ECHO" in evo.dynamic_skills
        assert "MCP.DUMMY.ECHO" in evo.toolbox.external

        # 再次修改 allow 为空，应卸载工具
        monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_ALLOW_TOOLS", [])
        for _ in range(50):
            if "MCP.DUMMY.ECHO" not in evo.tool_schemas:
                break
            await asyncio.sleep(0.05)
        assert "MCP.DUMMY.ECHO" not in evo.tool_schemas

        mgr.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(run())
