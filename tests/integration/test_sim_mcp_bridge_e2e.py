"""步骤 4：Sim MCP 端到端占位（单次 tools/call）。

默认 **skip**；在具备 AdamI MCP Server + Sim 画布联调环境时设 ``ADAMI_SIM_MCP_E2E=1`` 再实现具体断言。
"""

from __future__ import annotations

import os

import pytest


@pytest.mark.integration
def test_sim_mcp_single_tool_call_e2e_placeholder() -> None:
    """关键检测锚点：真实 E2E 在此处接 MCP SDK + Sim（当前占位 skip）。"""
    if os.environ.get("ADAMI_SIM_MCP_E2E") != "1":
        pytest.skip(
            "Set ADAMI_SIM_MCP_E2E=1 with Sim + AdamI MCP server (see docs/sim_mcp_bridge.md)"
        )
    pytest.skip(
        "E2E harness pending: implement single tools/call against AdamI MCP server (path A) "
        "or HTTP gateway (path B); see docs/sim_mcp_bridge.md"
    )
