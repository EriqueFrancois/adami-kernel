"""验收：第一 / 第二模块说明文档（mcp-use 生态与 lastmile mcp-agent）。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MOD1 = ROOT / "docs" / "mcp_module1_mcp_use.md"
MOD2 = ROOT / "docs" / "mcp_module2_lastmile_mcp_agent.md"
ALIGN = ROOT / "docs" / "mcp_agent_alignment.md"


def test_ac_mod_docs_both_exist() -> None:
    assert MOD1.is_file()
    assert MOD2.is_file()


def test_ac_mod_docs_alignment_links_modules() -> None:
    body = ALIGN.read_text(encoding="utf-8")
    assert "mcp_module1_mcp_use.md" in body
    assert "mcp_module2_lastmile_mcp_agent.md" in body


def test_ac_mod1_covers_native_and_upstream() -> None:
    t = MOD1.read_text(encoding="utf-8")
    assert "mcp-use" in t.lower() or "mcp-use" in t
    assert "ADAMI_MCP_ENABLED" in t
    assert "McpManager" in t or "第一模块" in t


def test_ac_mod2_covers_flags_and_helpers() -> None:
    t = MOD2.read_text(encoding="utf-8")
    assert "ADAMI_MCP_MODULE_AGENT_ENABLED" in t
    assert "mcp_agent_tool_execution_effective" in t
    assert "lastmile" in t.lower() or "mcp-agent" in t
