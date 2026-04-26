"""步骤 2：Agent↔Tool 契约层单测。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adami_kernel.integration.mcp_agent.contracts import (
    ToolCapability,
    ToolContractRegistry,
    ToolInvocation,
    ToolResult,
    to_llm_prompt_fragment,
    tool_capability_mcp,
    tool_capability_native,
)


def test_native_and_mcp_capabilities_parallel_structure() -> None:
    """同一 schema/description 下，内置与 MCP 在契约层字段结构一致（除 source / mcp_*）。"""
    schema = {"type": "object", "properties": {"q": {"type": "string"}}, "required": ["q"]}
    desc = "search the web"
    native = tool_capability_native("WEB_SEARCH", schema, desc)
    mcp = tool_capability_mcp("MCP.FETCH.FETCH", schema, desc, "fetch", "fetch")
    assert native.tool_id == "WEB_SEARCH"
    assert native.source == "native"
    assert native.mcp_server is None
    assert mcp.tool_id == "MCP.FETCH.FETCH"
    assert mcp.source == "mcp"
    assert mcp.mcp_server == "fetch"
    assert mcp.mcp_tool_name == "fetch"
    assert native.json_schema == mcp.json_schema == schema
    assert native.description == mcp.description == desc
    assert native.risk_tier == mcp.risk_tier
    assert native.requires_approval == mcp.requires_approval


def test_tool_invocation_and_result_models() -> None:
    inv = ToolInvocation(tool_id="X", args={"a": 1}, trace_id="t1", chat_id="c1")
    assert inv.tool_id == "X"
    res = ToolResult(structured={"ok": True}, text="ok", error_code=None)
    assert res.text == "ok"


def test_to_llm_prompt_fragment_matches_legacy_shape() -> None:
    caps = [
        tool_capability_native(
            "WEB_SEARCH",
            {"type": "object", "properties": {"query": {"type": "string"}}},
            "web",
        )
    ]
    frag = to_llm_prompt_fragment(caps)
    assert (
        "【🛠️ 已注册工具（JSON Schema 格式）】" in frag
        or "【🛠️ Registered tools (JSON Schema)】" in frag
    )
    assert ("工具: WEB_SEARCH" in frag) or ("Tool: WEB_SEARCH" in frag)
    assert ("LLM 必须严格按照 Schema 输出参数！" in frag) or (
        "The LLM must follow each tool Schema exactly" in frag
    )
    assert "query" in frag


def test_to_llm_prompt_fragment_max_chars_truncates() -> None:
    caps = [tool_capability_native(f"T{i}", {"type": "object"}, "d") for i in range(20)]
    frag = to_llm_prompt_fragment(caps, max_chars=200)
    assert len(frag) <= 250
    assert ("截断" in frag) or ("truncated" in frag.lower())


def test_registry_exposed_only_and_clear_source() -> None:
    reg = ToolContractRegistry()
    reg.register(
        ToolCapability(
            tool_id="A",
            source="native",
            json_schema={},
            description="",
            exposed=True,
        )
    )
    reg.register(
        ToolCapability(
            tool_id="B",
            source="native",
            json_schema={},
            description="",
            exposed=False,
        )
    )
    reg.register(tool_capability_mcp("MCP.S.E", {"type": "object"}, "d", "s", "e", exposed=True))
    exposed_ids = {c.tool_id for c in reg.list_exposed()}
    assert exposed_ids == {"A", "MCP.S.E"}
    n = reg.clear_source("mcp")
    assert n == 1
    assert reg.get("MCP.S.E") is None
    assert reg.get("A") is not None


def test_allowlist_semantics_exposed_false_hidden_from_llm_fragment() -> None:
    """2.2：契约层 exposed=False 不出现在 to_llm_prompt_fragment（与 deny 过滤后仅注册 exposed 工具一致）。"""
    reg = ToolContractRegistry()
    reg.register(tool_capability_native("PUBLIC", {"type": "object"}, "ok", exposed=True))
    reg.register(tool_capability_native("SECRET", {"type": "object"}, "nope", exposed=False))
    frag = to_llm_prompt_fragment(reg.list_exposed_sorted())
    assert "PUBLIC" in frag
    assert "SECRET" not in frag


def test_contract_list_aligns_with_tool_schemas_when_synced_via_evolution(
    tmp_path: Path,
) -> None:
    """注册进 EvolutionEngine 后，契约暴露列表与 tool_schemas 键一致（仅 exposed 工具）。"""
    from adami_kernel.cortex.evolution import EvolutionEngine

    ee = EvolutionEngine(toolbox=None, base_dir=str(tmp_path))
    schema = {"type": "object", "properties": {"x": {"type": "string"}}}
    ee.register_tool("ALPHA", schema, "alpha tool")
    ee.register_tool(
        "MCP.Z.Z",
        schema,
        "[MCP:z] z",
        tool_source="mcp",
        mcp_server="z",
        mcp_tool_name="z",
    )
    assert set(ee.tool_schemas.keys()) == {"ALPHA", "MCP.Z.Z"}
    reg_ids = {c.tool_id for c in ee.tool_contract_registry.list_exposed()}
    assert reg_ids == {"ALPHA", "MCP.Z.Z"}
    llm = ee.get_registered_tools_for_llm()
    assert "ALPHA" in llm and "MCP.Z.Z" in llm
    parsed = json.loads(json.dumps(ee.tool_schemas["ALPHA"]["json_schema"]))
    assert parsed == schema


@pytest.mark.asyncio
async def test_toolbox_optional_contract_registry_skip_duplicate() -> None:
    """已存在契约时，ToolboxManager 不再重复写入（MCP 主路径仅由 register_tool 写契约）。"""
    from adami_kernel.cortex.tools_manager import ToolboxManager
    from adami_kernel.integration.mcp_agent.contracts import ToolContractRegistry

    reg = ToolContractRegistry()
    reg.register(
        tool_capability_mcp(
            "MCP.DUMMY.ECHO",
            {"type": "object"},
            "d",
            "dummy",
            "echo",
        )
    )
    tb = ToolboxManager(sandbox_dir=".adami_test_sandbox")

    async def ex(text: str = "") -> str:
        return text

    tb.register_external_tools(
        source="mcp:dummy",
        tools=[{"name": "MCP.DUMMY.ECHO", "json_schema": {"type": "object"}, "description": "d"}],
        executors={"MCP.DUMMY.ECHO": ex},
        contract_registry=reg,
        sync_contract=True,
    )
    assert len(reg) == 1
