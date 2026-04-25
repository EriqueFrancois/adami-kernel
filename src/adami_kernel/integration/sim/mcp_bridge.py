"""Sim MCP 互操作技术桩（步骤 4）。实现见 docs/sim_mcp_bridge.md 路径 A / B。"""

from __future__ import annotations

from enum import Enum

SIM_MCP_BRIDGE_DOC = "docs/sim_mcp_bridge.md"


class SimMcpBridgePath(str, Enum):
    """与 ``docs/sim_mcp_bridge.md`` 两条路径对应。"""

    ADAMI_AS_MCP_SERVER = "path_a_adami_mcp_server"
    HTTP_TOOL_GATEWAY = "path_b_http_tool_gateway"
