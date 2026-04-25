"""验收：步骤 2（离线回放骨架 + 断言 DSL）。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPLAY_MOD = ROOT / "src" / "adami_kernel" / "integration" / "sim" / "replay.py"
REPLAY_CLI = ROOT / "src" / "adami_kernel" / "integration" / "sim" / "replay_cli.py"
SCRIPT = ROOT / "scripts" / "replay_trace.py"
GOLDEN = ROOT / "tests" / "replay" / "fixtures" / "golden_trace.ndjson"


def test_ac_sim_2_1_replay_module_and_golden_exist() -> None:
    assert REPLAY_MOD.is_file()
    assert REPLAY_CLI.is_file()
    assert SCRIPT.is_file()
    assert GOLDEN.is_file()


def test_ac_sim_2_2_replay_exports_assertion_and_inject() -> None:
    body = REPLAY_MOD.read_text(encoding="utf-8")
    assert "class TraceAssertion" in body
    assert "def replay_inject" in body
    assert "def validate_phase1_records" in body
    assert "FaultInjectionOptions" in body


def test_ac_sim_2_3_pyproject_registers_cli() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "adami-replay-validate" in text
    assert "replay_cli:main" in text


def test_ac_sim_2_4_integration_sim_exports_replay_api() -> None:
    from adami_kernel.integration import sim as sim_pkg

    for name in (
        "load_ndjson_records",
        "validate_phase1_records",
        "TraceAssertion",
        "replay_inject",
        "assert_record_matches",
        "apply_assertions",
        "ReplayValidationError",
    ):
        assert hasattr(sim_pkg, name), f"missing integration.sim.{name}"


def test_ac_sim_2_5_golden_fixture_is_valid_v1_ndjson() -> None:
    import json

    from adami_kernel.integration.sim.schema import TRACE_SCHEMA_V1

    lines = [ln for ln in GOLDEN.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 1
    for ln in lines:
        obj = json.loads(ln)
        assert obj.get("schema_version") == TRACE_SCHEMA_V1
        assert obj.get("trace_id")
        assert obj.get("source_module")
        assert obj.get("target_topic") is not None


def test_ac_sim_2_6_replay_cli_main_exits_zero_on_golden() -> None:
    from adami_kernel.integration.sim.replay_cli import main

    assert main([str(GOLDEN)]) == 0
