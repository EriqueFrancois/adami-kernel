"""验收：步骤 2（Agent↔Tool 契约层）。

验收方案
--------
**AC-2.1 契约模块可导入**
``ToolCapability`` / ``ToolInvocation`` / ``ToolResult`` / ``ToolContractRegistry`` / ``to_llm_prompt_fragment`` /
工厂函数可从 ``adami_kernel.integration.mcp_agent.contracts`` 导入。

**AC-2.2 EvolutionEngine 与契约同步**
``register_tool`` 后 ``tool_contract_registry`` 与 ``tool_schemas`` 对同一 ``tool_id`` 一致；
``tool_source=\"mcp\"`` 时契约含 ``mcp_server`` / ``mcp_tool_name``。

**AC-2.3 get_registered_tools_for_llm 走契约层**
在存在暴露契约时，输出含历史格式锚点（「已注册工具」、``工具:``、``LLM 必须严格按照 Schema``），且提及已注册工具名。

**AC-2.4 2.1 截断与 Planner 策略可控**
``to_llm_prompt_fragment(..., max_chars=N)`` 超长时含「截断」提示（与 Planner 侧可叠加 ``MAX_TOOLS_LENGTH`` 一致）。

**AC-2.5 2.2 exposed 与 LLM 可见性**
``exposed=False`` 的契约不出现在 ``to_llm_prompt_fragment(list_exposed_sorted())`` 中。

**AC-2.6 MCP 卸载与契约**
``McpManager._unregister_all`` 对带 ``tool_contract_registry`` 的引擎调用 ``clear_source(\"mcp\")``（Fake 双测）。

**AC-2.7 对齐文档**
``docs/mcp_agent_alignment.md`` 提及 ``contracts.py`` 或 ``ToolContractRegistry``。

**建议人工**
- 真机 ``ADAMI_MCP_ENABLED`` + Docker 下刷新 MCP 后，``tool_schemas`` 与契约表工具集合一致
  （与 ``test_mcp_manager_background_reload`` 同类）。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import adami_kernel.integration.mcp_agent.contracts as contracts_mod
from adami_kernel.integration.mcp_agent.contracts import (
    ToolContractRegistry,
    ToolInvocation,
    ToolResult,
    to_llm_prompt_fragment,
    tool_capability_mcp,
    tool_capability_native,
)
from adami_kernel.mcp.manager import McpManager


def test_ac_2_1_public_api_surface() -> None:
    assert hasattr(contracts_mod, "legacy_fragment_from_tool_schemas")
    assert hasattr(contracts_mod, "tool_capability_external")
    _ = ToolInvocation(tool_id="t", args={})
    _ = ToolResult(text="x")


def test_ac_2_2_evolution_registry_sync_native_and_mcp(tmp_path: Path) -> None:
    from adami_kernel.cortex.evolution import EvolutionEngine

    ee = EvolutionEngine(toolbox=None, base_dir=str(tmp_path))
    sch = {"type": "object", "properties": {"q": {"type": "string"}}}
    ee.register_tool("NATIVE_T", sch, "n")
    cap_n = ee.tool_contract_registry.get("NATIVE_T")
    assert cap_n is not None
    assert cap_n.source == "native"
    assert cap_n.json_schema == sch

    ee.register_tool(
        "MCP.SRV.TOOL",
        sch,
        "m",
        tool_source="mcp",
        mcp_server="srv",
        mcp_tool_name="tool",
    )
    cap_m = ee.tool_contract_registry.get("MCP.SRV.TOOL")
    assert cap_m is not None
    assert cap_m.source == "mcp"
    assert cap_m.mcp_server == "srv"
    assert cap_m.mcp_tool_name == "tool"
    assert set(ee.tool_schemas.keys()) >= {"NATIVE_T", "MCP.SRV.TOOL"}


def test_ac_2_3_get_registered_tools_for_llm_from_contracts(tmp_path: Path) -> None:
    from adami_kernel.cortex.evolution import EvolutionEngine

    ee = EvolutionEngine(toolbox=None, base_dir=str(tmp_path))
    ee.register_tool("ZETA", {"type": "object"}, "z")
    text = ee.get_registered_tools_for_llm()
    assert "【🛠️ 已注册工具（JSON Schema 格式）】" in text
    assert "工具: ZETA" in text
    assert "LLM 必须严格按照 Schema 输出参数！" in text


def test_ac_2_4_truncation_hint() -> None:
    caps = [tool_capability_native(f"ID{i}", {"type": "object"}, "d") for i in range(30)]
    frag = to_llm_prompt_fragment(caps, max_chars=180)
    assert "截断" in frag
    assert len(frag) <= 280


def test_ac_2_5_exposed_hides_from_llm_fragment() -> None:
    reg = ToolContractRegistry()
    reg.register(tool_capability_native("OK", {"type": "object"}, "x", exposed=True))
    reg.register(tool_capability_native("HIDDEN", {"type": "object"}, "y", exposed=False))
    frag = to_llm_prompt_fragment(reg.list_exposed_sorted())
    assert "OK" in frag
    assert "HIDDEN" not in frag


def test_ac_2_6_mcp_manager_clears_contract_source_mcp() -> None:
    class _Tb:
        def unregister_external_tools(self, *, source_prefix: str) -> int:
            return 0

    class _Evo:
        def __init__(self) -> None:
            self.tool_schemas: dict[str, object] = {}
            self.dynamic_skills: dict[str, object] = {}
            self.toolbox = _Tb()
            self.tool_contract_registry = ToolContractRegistry()

        def register_tool(self, *a: object, **k: object) -> None:
            pass

    evo = _Evo()
    evo.tool_contract_registry.register(
        tool_capability_mcp("MCP.X.Y", {"type": "object"}, "d", "x", "y")
    )
    assert evo.tool_contract_registry.get("MCP.X.Y") is not None

    mgr = McpManager(evolution_engine=evo)

    async def run() -> None:
        mgr._unregister_all()

    asyncio.run(run())
    assert evo.tool_contract_registry.get("MCP.X.Y") is None


def test_ac_2_7_alignment_doc_mentions_contracts() -> None:
    p = Path(__file__).resolve().parents[1] / "docs" / "mcp_agent_alignment.md"
    body = p.read_text(encoding="utf-8")
    assert "contracts.py" in body or "ToolContractRegistry" in body or "ToolCapability" in body
