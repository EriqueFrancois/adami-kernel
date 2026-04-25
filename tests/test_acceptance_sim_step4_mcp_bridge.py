"""验收：步骤 4（Sim MCP 互操作文档 + 技术桩）。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "sim_mcp_bridge.md"
STUB = ROOT / "src" / "adami_kernel" / "integration" / "sim" / "mcp_bridge.py"
PLAN = ROOT / "docs" / "sim_integration_plan.md"


def test_ac_sim_4_1_mcp_bridge_doc_exists() -> None:
    assert DOC.is_file()


def test_ac_sim_4_2_doc_covers_paths_a_b_and_modules() -> None:
    t = DOC.read_text(encoding="utf-8")
    assert "路径 A" in t or "路径A" in t
    assert "路径 B" in t or "路径B" in t
    assert "docs.sim.ai/mcp" in t or "sim.ai/mcp" in t
    assert "McpManager" in t or "模块一" in t
    assert "mcp-agent" in t or "模块二" in t


def test_ac_sim_4_3_stub_module_exports_enum() -> None:
    from adami_kernel.integration.sim.mcp_bridge import SIM_MCP_BRIDGE_DOC, SimMcpBridgePath

    assert SIM_MCP_BRIDGE_DOC == "docs/sim_mcp_bridge.md"
    assert SimMcpBridgePath.ADAMI_AS_MCP_SERVER.value.startswith("path_a")


def test_ac_sim_4_4_plan_documents_step4() -> None:
    body = PLAN.read_text(encoding="utf-8")
    assert "sim_mcp_bridge.md" in body


def test_ac_sim_4_5_integration_sim_exports_bridge_symbols() -> None:
    from adami_kernel.integration import sim as sim_pkg

    assert hasattr(sim_pkg, "SimMcpBridgePath")
    assert hasattr(sim_pkg, "SIM_MCP_BRIDGE_DOC")


def test_ac_sim_4_6_pytest_integration_marker_registered() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "integration" in text and "markers" in text


def test_ac_sim_4_7_module_docs_cross_link_sim_mcp_bridge() -> None:
    m1 = (ROOT / "docs" / "mcp_module1_mcp_use.md").read_text(encoding="utf-8")
    m2 = (ROOT / "docs" / "mcp_module2_lastmile_mcp_agent.md").read_text(encoding="utf-8")
    assert "sim_mcp_bridge.md" in m1
    assert "sim_mcp_bridge.md" in m2


def test_ac_sim_4_8_integration_e2e_file_has_marker() -> None:
    e2e = ROOT / "tests" / "integration" / "test_sim_mcp_bridge_e2e.py"
    assert e2e.is_file()
    body = e2e.read_text(encoding="utf-8")
    assert "@pytest.mark.integration" in body
    assert "ADAMI_SIM_MCP_E2E" in body
