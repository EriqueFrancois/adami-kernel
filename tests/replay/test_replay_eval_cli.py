from __future__ import annotations

from pathlib import Path


FIXTURES = Path(__file__).resolve().parent / "fixtures"
DOC_ASSERTIONS = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "evals"
    / "traces"
    / "minimal"
    / "assertions.json"
)
DOC_TRACE_SUITE_DIR = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "evals"
    / "traces"
)


def test_replay_eval_cli_passes_on_golden(tmp_path: Path) -> None:
    from adami_kernel.integration.sim.replay_eval_cli import main

    out_json = tmp_path / "report.json"
    out_md = tmp_path / "report.md"
    code = main(
        [
            str(FIXTURES / "golden_trace.ndjson"),
            "--assertions",
            str(DOC_ASSERTIONS),
            "--forbid",
            "sk-",
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ]
    )
    assert code == 0
    assert out_json.is_file()
    assert out_md.is_file()


def test_replay_eval_cli_suite_dir_passes(tmp_path: Path) -> None:
    from adami_kernel.integration.sim.replay_eval_cli import main

    out_json = tmp_path / "suite.json"
    out_md = tmp_path / "suite.md"
    code = main(
        [
            "--suite-dir",
            str(DOC_TRACE_SUITE_DIR),
            "--forbid",
            "sk-",
            "--out-json",
            str(out_json),
            "--out-md",
            str(out_md),
        ]
    )
    assert code == 0
    assert out_json.is_file()
    assert out_md.is_file()
    body = out_json.read_text(encoding="utf-8")
    assert '"scorecard"' in body
    assert '"correctness"' in body

