"""验收：步骤 5（CI replay job + stress 标记）。"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WF = ROOT / ".github" / "workflows" / "kernel-ci.yml"
CI_ROOT = ROOT / "ci.yml"
STRESS = ROOT / "tests" / "stress" / "test_replay_stress.py"


def test_ac_sim_5_1_workflow_defines_replay_traces_job() -> None:
    text = WF.read_text(encoding="utf-8")
    assert "replay-traces:" in text
    assert "tests/replay/" in text
    assert "test_acceptance_sim_step2_replay.py" in text


def test_ac_sim_5_2_root_ci_matches_workflow_or_documents_sync() -> None:
    assert CI_ROOT.is_file()
    root = CI_ROOT.read_text(encoding="utf-8")
    assert "replay-traces:" in root
    assert "not integration and not stress" in root


def test_ac_sim_5_3_stress_module_and_marker() -> None:
    assert STRESS.is_file()
    body = STRESS.read_text(encoding="utf-8")
    assert "@pytest.mark.stress" in body
    assert "STRESS_FAILURE_THRESHOLD" in body


def test_ac_sim_5_4_pyproject_registers_stress_marker() -> None:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert "stress" in text and "markers" in text
