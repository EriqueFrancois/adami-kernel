from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run(cmd: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, check=False, text=True, capture_output=True)


def test_replay_run_cli_exports_trace(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    trace = root / "docs" / "evals" / "traces" / "tool_timeout" / "golden_trace.ndjson"
    out = tmp_path / "replayed.ndjson"

    cp = _run(
        [
            sys.executable,
            "-m",
            "adami_kernel.integration.sim.replay_run_cli",
            str(trace),
            "--out-trace",
            str(out),
        ]
    )
    assert cp.returncode == 0, cp.stderr
    assert out.is_file()
    lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 1
    obj = json.loads(lines[0])
    assert obj.get("schema_version") == "adami_replay_trace.v1"


def test_replay_run_cli_full_kernel_toolchoice(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    trace = root / "docs" / "evals" / "traces" / "toolchoice" / "golden_trace.ndjson"
    out = tmp_path / "toolchoice.replayed.ndjson"

    cp = _run(
        [
            sys.executable,
            "-m",
            "adami_kernel.integration.sim.replay_run_cli",
            str(trace),
            "--out-trace",
            str(out),
            "--full-kernel",
            "--verify-isomorphic",
        ]
    )
    assert cp.returncode == 0, cp.stderr
    lines = [ln for ln in out.read_text(encoding="utf-8").splitlines() if ln.strip()]
    assert len(lines) >= 8
    # Ensure the replayed trace includes LLM tool lifecycle events.
    assert any('"event_type":"TOOL_CALL_START"' in ln and '"tool":"llm.think"' in ln for ln in lines)


def test_replay_run_cli_verify_isomorphic_planner_multistep(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    trace = root / "docs" / "evals" / "traces" / "planner_multistep" / "golden_trace.ndjson"
    out = tmp_path / "planner_multistep.replayed.ndjson"

    cp = _run(
        [
            sys.executable,
            "-m",
            "adami_kernel.integration.sim.replay_run_cli",
            str(trace),
            "--out-trace",
            str(out),
            "--verify-isomorphic",
        ]
    )
    assert cp.returncode == 0, cp.stderr
    assert out.is_file()


def test_replay_run_cli_verify_isomorphic_planner_multistep_mcp(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    trace = root / "docs" / "evals" / "traces" / "planner_multistep_mcp" / "golden_trace.ndjson"
    out = tmp_path / "planner_multistep_mcp.replayed.ndjson"

    cp = _run(
        [
            sys.executable,
            "-m",
            "adami_kernel.integration.sim.replay_run_cli",
            str(trace),
            "--out-trace",
            str(out),
            "--verify-isomorphic",
        ]
    )
    assert cp.returncode == 0, cp.stderr
    assert out.is_file()


def test_replay_run_cli_inject_all_records_isomorphic_toolchoice(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    trace = root / "docs" / "evals" / "traces" / "toolchoice" / "golden_trace.ndjson"
    out = tmp_path / "toolchoice.inject_all.ndjson"

    cp = _run(
        [
            sys.executable,
            "-m",
            "adami_kernel.integration.sim.replay_run_cli",
            str(trace),
            "--out-trace",
            str(out),
            "--inject-all-records",
            "--verify-isomorphic",
        ]
    )
    assert cp.returncode == 0, cp.stderr
    assert out.is_file()


def test_replay_run_cli_fault_injection_outputs_eval_reports(tmp_path: Path) -> None:
    root = Path(__file__).resolve().parents[2]
    trace = root / "docs" / "evals" / "traces" / "planner_multistep" / "golden_trace.ndjson"
    faults = tmp_path / "faults.json"
    faults.write_text('{"enabled": true, "skip_indices": [6]}\n', encoding="utf-8")

    out = tmp_path / "faulted.ndjson"
    out_eval_json = tmp_path / "faulted.eval.json"
    out_eval_md = tmp_path / "faulted.eval.md"

    cp = _run(
        [
            sys.executable,
            "-m",
            "adami_kernel.integration.sim.replay_run_cli",
            str(trace),
            "--out-trace",
            str(out),
            "--faults",
            str(faults),
            "--out-eval-json",
            str(out_eval_json),
            "--out-eval-md",
            str(out_eval_md),
        ]
    )
    # We expect the eval to fail (missing BRANCH_DECISION), but outputs must exist.
    assert cp.returncode == 2, cp.stderr
    assert out.is_file()
    assert out_eval_json.is_file()
    assert out_eval_md.is_file()

