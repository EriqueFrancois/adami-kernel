"""验收：步骤 7（渐进替换策略文档 + 对齐文档交叉引用）。

自动项：工件存在、必备章节关键词、``mcp_agent_alignment`` 指向步骤 7。
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STEP7 = ROOT / "docs" / "mcp_agent_step7_migration.md"
ALIGNMENT = ROOT / "docs" / "mcp_agent_alignment.md"


def test_ac_7_1_step7_migration_doc_exists() -> None:
    assert STEP7.is_file(), "docs/mcp_agent_step7_migration.md 应存在"


def test_ac_7_2_alignment_links_step7_doc() -> None:
    body = ALIGNMENT.read_text(encoding="utf-8")
    assert "mcp_agent_step7_migration.md" in body
    assert "步骤 7" in body


def test_ac_7_3_migration_doc_covers_flags_checklist_and_parity() -> None:
    body = STEP7.read_text(encoding="utf-8")
    assert "ADAMI_USE_MCP_AGENT" in body
    assert "ADAMI_MCP_ENABLED" in body
    assert "ADAMI_MCP_MODULE_AGENT_ENABLED" in body
    assert "双写" in body or "dual" in body.lower()
    assert "Checklist" in body or "清单" in body
    assert "mcp_agent_config" in body or "docker_run_args" in body
    assert "工具列表" in body or "tool_id" in body
    assert "调用" in body or "tools/call" in body


def test_ac_7_4_migration_doc_section_outline_and_scope() -> None:
    """§1–§5 标题存在；边界声明（文档期不删代码）；建议 flag 与审计关键词。"""
    body = STEP7.read_text(encoding="utf-8")
    assert "## 1." in body and "目标" in body
    assert "## 2." in body and "双栈" in body
    assert "## 3." in body and "Feature flag" in body
    assert "## 4." in body and "关键检测" in body
    assert "## 5." in body
    assert "不在此阶段改代码" in body or "不在该文档阶段删代码" in body
    assert "ADAMI_USE_MCP_AGENT_PLANNER" in body
    assert "experience_sink" in body
    assert "ADAMI_MCP_EXECUTION_MODE" in body


def test_ac_7_5_migration_doc_links_regression_and_code_paths() -> None:
    body = STEP7.read_text(encoding="utf-8")
    assert "contracts.py" in body
    assert "tool_executor.py" in body
    assert "test_acceptance_mcp_agent_step6_smoke_matrix" in body
