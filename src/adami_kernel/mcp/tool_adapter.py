from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

import adami_kernel.config as config_mod
from adami_kernel.mcp.docker_stdio_runner import McpDockerStdioRunner
from adami_kernel.mcp.spec import McpServerSpec

logger = logging.getLogger("AdamI-MCP")


def _is_allowed(tool_name: str) -> bool:
    # allow/deny 支持大小写不敏感匹配
    t = (tool_name or "").strip().lower()
    deny = {
        str(x).strip().lower()
        for x in (config_mod.settings.ADAMI_MCP_DENY_TOOLS or [])
        if str(x).strip()
    }
    allow = {
        str(x).strip().lower()
        for x in (config_mod.settings.ADAMI_MCP_ALLOW_TOOLS or [])
        if str(x).strip()
    }
    if t in deny:
        return False
    # deny 永远优先：若 deny 里包含短名（echo），也应禁止所有映射名（mcp.<server>.echo）
    if "." in t:
        short = t.split(".")[-1]
        if short in deny:
            return False
    if not allow:
        return False
    return t in allow


def map_tool_name(spec: McpServerSpec, mcp_tool_name: str) -> str:
    # 避免与现有工具名冲突：加入 server 前缀
    # 建议命名：mcp.<server>.<tool>
    return f"mcp.{spec.name}.{mcp_tool_name}".upper()


async def list_mcp_tools(runner: McpDockerStdioRunner, spec: McpServerSpec) -> List[Dict[str, Any]]:
    resp = await runner.request(spec, method="tools/list", params={})
    if resp.error:
        raise RuntimeError(resp.error.get("message", "tools/list failed"))
    tools = resp.result or []
    if not isinstance(tools, list):
        return []
    return tools


async def call_mcp_tool(
    runner: McpDockerStdioRunner, spec: McpServerSpec, *, tool_name: str, arguments: Dict[str, Any]
) -> Any:
    resp = await runner.request(
        spec, method="tools/call", params={"name": tool_name, "arguments": arguments}
    )
    if resp.error:
        raise RuntimeError(resp.error.get("message", "tools/call failed"))
    return resp.result


async def build_adami_tool_registrations(
    runner: McpDockerStdioRunner, spec: McpServerSpec
) -> List[Tuple[str, Dict[str, Any], str, str]]:
    """返回给 EvolutionEngine.register_tool 使用的元组列表：
    (adami_tool_name, json_schema, description, mcp_tool_name)
    """
    out: List[Tuple[str, Dict[str, Any], str, str]] = []
    for t in await list_mcp_tools(runner, spec):
        mcp_name = str(t.get("name") or "").strip()
        if not mcp_name:
            continue
        adami_name = map_tool_name(spec, mcp_name)
        # 允许按 MCP 原名（echo）或映射后的完整名（mcp.dummy.echo）配置 allow/deny
        if not _is_allowed(mcp_name) and not _is_allowed(adami_name):
            continue
        desc = str(t.get("description") or "")
        schema = t.get("inputSchema") or t.get("input_schema") or {}
        if not isinstance(schema, dict):
            schema = {}
        if "type" not in schema:
            schema = {
                "type": "object",
                "properties": schema.get("properties", {}),
                "required": schema.get("required", []),
            }
        out.append((adami_name, schema, f"[MCP:{spec.name}] {desc}".strip(), mcp_name))
    return out
