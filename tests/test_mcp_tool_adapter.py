from __future__ import annotations

import pytest

import adami_kernel.config as config_mod
from adami_kernel.mcp.spec import McpServerSpec
from adami_kernel.mcp.tool_adapter import map_tool_name


def test_map_tool_name_prefix_and_no_conflict_between_servers() -> None:
    a = McpServerSpec(name="a", image="x", command=["python"])
    b = McpServerSpec(name="b", image="x", command=["python"])
    assert map_tool_name(a, "echo") == "MCP.A.ECHO"
    assert map_tool_name(b, "echo") == "MCP.B.ECHO"
    assert map_tool_name(a, "echo") != map_tool_name(b, "echo")


def test_allow_deny_case_insensitive(monkeypatch: pytest.MonkeyPatch) -> None:
    # allow echo (mixed case) should allow mapped name too
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_ALLOW_TOOLS", ["EcHo"])
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_DENY_TOOLS", [])

    from adami_kernel.mcp import tool_adapter as ta

    assert ta._is_allowed("echo") is True
    assert ta._is_allowed("ECHO") is True
    assert ta._is_allowed("mcp.dummy.echo") is False  # not explicitly allowed by full name here

    # allow full mapped name
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_ALLOW_TOOLS", ["mcp.dummy.echo"])
    assert ta._is_allowed("mcp.dummy.echo") is True
    assert ta._is_allowed("MCP.DUMMY.ECHO") is True

    # deny always wins
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_DENY_TOOLS", ["echo"])
    assert ta._is_allowed("echo") is False
    assert ta._is_allowed("mcp.dummy.echo") is False


def test_default_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_ALLOW_TOOLS", [])
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_DENY_TOOLS", [])
    from adami_kernel.mcp import tool_adapter as ta

    assert ta._is_allowed("echo") is False
