from __future__ import annotations

import pytest

import adami_kernel.config as config_mod
from adami_kernel.mcp import tool_adapter as ta


def test_default_deny(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_ALLOW_TOOLS", [])
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_DENY_TOOLS", [])
    assert ta._is_allowed("echo") is False
    assert ta._is_allowed("mcp.dummy.echo") is False


def test_allow_short_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_ALLOW_TOOLS", ["echo"])
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_DENY_TOOLS", [])
    assert ta._is_allowed("echo") is True
    assert ta._is_allowed("ECHO") is True


def test_allow_full_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_ALLOW_TOOLS", ["mcp.dummy.echo"])
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_DENY_TOOLS", [])
    assert ta._is_allowed("mcp.dummy.echo") is True
    assert ta._is_allowed("MCP.DUMMY.ECHO") is True


def test_deny_wins_and_short_deny_blocks_full(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_ALLOW_TOOLS", ["mcp.dummy.echo", "echo"])
    monkeypatch.setattr(config_mod.settings, "ADAMI_MCP_DENY_TOOLS", ["echo"])
    assert ta._is_allowed("echo") is False
    assert ta._is_allowed("mcp.dummy.echo") is False
