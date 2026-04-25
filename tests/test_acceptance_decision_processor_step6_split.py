"""
Step 6 acceptance: DecisionProcessor split (support + report actions, lazy imports, stable public surface).

Run: poetry run python -m pytest tests/test_acceptance_decision_processor_step6_split.py -q
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def _root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_ac6_support_module_defines_intake_helper() -> None:
    text = (
        _root() / "src" / "adami_kernel" / "cortex" / "decision_processor_support.py"
    ).read_text(encoding="utf-8")
    assert "async def _intake_archive_body_from_payload" in text
    assert "class TaskFailedException" in text
    assert "class SkillCreationPlan" in text


def test_ac6_report_actions_defines_runner() -> None:
    text = (
        _root() / "src" / "adami_kernel" / "cortex" / "decision_processor_report_actions.py"
    ).read_text(encoding="utf-8")
    assert "async def run_report_action" in text
    assert (
        "from adami_kernel.peripheral.report_studio.report_store import ReportConfigStore" in text
    )


def test_ac6_decision_processor_reexports_intake_helper() -> None:
    from adami_kernel.cortex import decision_processor as dp

    assert hasattr(dp, "_intake_archive_body_from_payload")
    assert callable(dp._intake_archive_body_from_payload)


def test_ac6_decision_processor_exposes_get_experience_sink_for_monkeypatch() -> None:
    """Guards rely on patching ``adami_kernel.cortex.decision_processor.get_experience_sink``."""
    from adami_kernel.cortex import decision_processor as dp

    assert hasattr(dp, "get_experience_sink")
    assert callable(dp.get_experience_sink)


def test_ac6_import_decision_processor_does_not_load_report_generator_subprocess() -> None:
    """Heavy report stack (e.g. aiosqlite) must not load until /report run path."""
    repo = str(_root())
    code = (
        "import sys\n"
        "from adami_kernel.cortex.decision_processor import DecisionProcessor\n"
        "m = 'adami_kernel.peripheral.report_studio.report_generator'\n"
        "assert m not in sys.modules, m\n"
        "assert DecisionProcessor is not None\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=repo,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
