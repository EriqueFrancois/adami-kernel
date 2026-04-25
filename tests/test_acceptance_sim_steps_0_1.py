"""验收：模块三 Sim 集成 — 步骤 0（边界文档）与步骤 1（EventBus 轨迹契约）。

与 ``tests/test_sim_trace_export.py`` 的关系：本文件做**工件与文档**验收；后者做**行为**验收。
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "docs" / "sim_integration_plan.md"
TASKLIST = ROOT / "tasklist.md"
SCHEMA = ROOT / "src" / "adami_kernel" / "integration" / "sim" / "schema.py"
TRACE_SINK = ROOT / "src" / "adami_kernel" / "integration" / "sim" / "trace_sink.py"
BUS = ROOT / "src" / "adami_kernel" / "nexus" / "bus.py"
CONFIG = ROOT / "src" / "adami_kernel" / "config.py"
ENV_EXAMPLE = ROOT / ".env.example"


def test_ac_sim_0_1_integration_plan_exists() -> None:
    assert PLAN.is_file()


def test_ac_sim_0_2_tasklist_links_plan() -> None:
    body = TASKLIST.read_text(encoding="utf-8")
    assert "docs/sim_integration_plan.md" in body


def test_ac_sim_0_3_plan_covers_dual_tracks_and_scope() -> None:
    body = PLAN.read_text(encoding="utf-8")
    assert "轨 A" in body and "轨 B" in body
    assert "从哪出" in body and "到哪止" in body
    assert "docs.sim.ai" in body
    assert "docs.sim.ai/mcp" in body or "sim.ai/mcp" in body
    assert "不是" in body and "仿真引擎" in body
    assert "主战场" in body or "AdamI 仓库内" in body


def test_ac_sim_0_4_plan_documents_step1_alignment() -> None:
    body = PLAN.read_text(encoding="utf-8")
    assert "4.1" in body or "步骤 1" in body
    assert "ExperienceSink" in body or "episode" in body.lower()


def test_ac_sim_1_1_schema_and_sink_modules_exist() -> None:
    assert SCHEMA.is_file()
    assert TRACE_SINK.is_file()
    assert (ROOT / "src" / "adami_kernel" / "integration" / "sim" / "__init__.py").is_file()


def test_ac_sim_1_2_config_defines_trace_flags() -> None:
    text = CONFIG.read_text(encoding="utf-8")
    assert "ADAMI_SIM_TRACE_EXPORT_ENABLED" in text
    assert "ADAMI_SIM_TRACE_EXPORT_PATH" in text
    assert "ADAMI_SIM_TRACE_MAX_QUEUE" in text
    assert "ADAMI_SIM_TRACE_TOPICS_ALLOWLIST" in text


def test_ac_sim_1_3_bus_wires_trace_sink() -> None:
    text = BUS.read_text(encoding="utf-8")
    assert "get_trace_sink" in text
    assert "offer_trace_event_for_system_path" in text
    assert "sink.middleware" in text or "sink" in text and "middleware" in text


def test_ac_sim_1_4_env_example_mentions_trace() -> None:
    assert ENV_EXAMPLE.is_file()
    assert "ADAMI_SIM_TRACE" in ENV_EXAMPLE.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "symbol",
    [
        "TRACE_SCHEMA_V1",
        "ReplayTraceRecordV1",
        "event_to_record",
        "get_trace_sink",
    ],
)
def test_ac_sim_1_5_public_sim_package_exports(symbol: str) -> None:
    from adami_kernel.integration import sim as sim_pkg

    assert hasattr(sim_pkg, symbol), f"missing integration.sim.{symbol}"
