# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false, reportUnknownArgumentType=false

"""单步 MCP 工具执行：经 mcp-agent ``Agent.call_tool``（官方会话/聚合器），失败返回 ``None`` 由主通路降级。"""

from __future__ import annotations

import json
import logging
from typing import Any, List, Optional

import adami_kernel.config as config_mod
from adami_kernel.integration.mcp_agent.contracts import ToolCapability, ToolInvocation

logger = logging.getLogger("AdamI-MCPAgentToolExec")


def _call_tool_result_to_plain(result: Any) -> str:  # noqa: ANN401  # CallToolResult / untyped MCP SDK
    """将 MCP ``CallToolResult`` 压成可展示字符串（Planner 与第一模块风格对齐）。"""
    if result is None:
        return ""
    structured = getattr(result, "structuredContent", None) or getattr(
        result, "structured_content", None
    )
    if isinstance(structured, dict) and structured:
        try:
            return json.dumps(structured, ensure_ascii=False)
        except (TypeError, ValueError):
            pass
    chunks: List[str] = []
    for block in getattr(result, "content", None) or []:
        txt = getattr(block, "text", None)
        if txt is not None:
            chunks.append(str(txt))
        else:
            chunks.append(str(block))
    out = "\n".join(chunks).strip()
    if getattr(result, "isError", None) or getattr(result, "is_error", None):
        return f"[MCP error] {out}" if out else "[MCP error]"
    return out if out else str(result)


def mcp_agent_tool_execution_enabled() -> bool:
    return config_mod.mcp_agent_tool_execution_effective(config_mod.settings)


async def try_execute_via_mcp_agent(
    inv: ToolInvocation,
    cap: ToolCapability,
) -> Optional[Any]:  # noqa: ANN401
    """若开关开启且契约为 MCP，则经 mcp-agent 执行；失败或跳过时返回 ``None``（调用方走 Docker/get_skill）。"""
    if not mcp_agent_tool_execution_enabled():
        return None
    if cap.source != "mcp" or not cap.mcp_server or not cap.mcp_tool_name:
        return None

    try:
        from mcp_agent.agents.agent import Agent  # type: ignore[import-untyped]
    except ImportError:
        logger.warning(
            "[MCPAgent][trace_id=%s] mcp-agent not installed; skip pilot",
            inv.trace_id or "-",
        )
        return None

    from adami_kernel.integration.mcp_agent.adapter import adamimcp_runtime

    try:
        async with adamimcp_runtime(app_name="adami_kernel_mcp_tool_exec") as (
            running_app,
            server_names,
        ):
            if cap.mcp_server not in server_names:
                logger.warning(
                    "[MCPAgent][trace_id=%s] server %r not in mcp-agent map %s; degrade",
                    inv.trace_id or "-",
                    cap.mcp_server,
                    server_names,
                )
                return None

            agent = Agent(
                name="adami_planner_tool_runner",
                instruction="Execute MCP tools as requested by the host planner.",
                server_names=server_names,
                context=running_app.context,
            )
            async with agent:
                logger.info(
                    "[MCPAgent][trace_id=%s] call_tool server=%r tool=%r args_keys=%s",
                    inv.trace_id or "-",
                    cap.mcp_server,
                    cap.mcp_tool_name,
                    list((inv.args or {}).keys()),
                )
                ctr = await agent.call_tool(
                    cap.mcp_tool_name,
                    inv.args or {},
                    server_name=cap.mcp_server,
                )
                text = _call_tool_result_to_plain(ctr)
                return text
    except Exception as e:
        logger.warning(
            "[MCPAgent][trace_id=%s] pilot tool exec failed (%s); degrading to native MCP runner",
            inv.trace_id or "-",
            e,
        )
        return None
