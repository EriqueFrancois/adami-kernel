from __future__ import annotations

from pathlib import Path


def test_golden_trace_refresh_cli_writes_traces(tmp_path: Path) -> None:
    from adami_kernel.integration.sim.golden_trace_refresh_cli import main

    # Copy minimal suite layout into temp dir.
    (tmp_path / "report_daily").mkdir(parents=True, exist_ok=True)
    (tmp_path / "intake").mkdir(parents=True, exist_ok=True)
    (tmp_path / "tool_timeout").mkdir(parents=True, exist_ok=True)

    code = main(["--traces-dir", str(tmp_path)])
    assert code == 0

    for name in ("report_daily", "intake", "tool_timeout"):
        p = tmp_path / name / "golden_trace.ndjson"
        assert p.is_file()
        assert p.read_text(encoding="utf-8").strip()

