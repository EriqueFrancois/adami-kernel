from __future__ import annotations

from pathlib import Path

from adami_kernel.integration.sim.replay_eval import evaluate_trace_file


def test_scorecard_min_cost_gate_on_llm_call(tmp_path: Path) -> None:
    # llm_call has llm_calls=1 -> cost_score=90 (per formula in replay_eval.py)
    trace = Path("docs/evals/traces/llm_call/golden_trace.ndjson")
    scorecard = tmp_path / "scorecard.json"
    scorecard.write_text('{"min_cost": 95}\n', encoding="utf-8")

    res = evaluate_trace_file(
        trace_file=trace,
        assertions_file=Path("docs/evals/traces/llm_call/assertions.json"),
        scorecard_file=scorecard,
    )
    assert res.ok is False
    assert "threshold_cost" in res.failures


def test_scorecard_max_llm_calls_gate(tmp_path: Path) -> None:
    trace = Path("docs/evals/traces/llm_call/golden_trace.ndjson")
    scorecard = tmp_path / "scorecard.json"
    scorecard.write_text('{"max_llm_calls": 0}\n', encoding="utf-8")

    res = evaluate_trace_file(
        trace_file=trace,
        assertions_file=Path("docs/evals/traces/llm_call/assertions.json"),
        scorecard_file=scorecard,
    )
    assert res.ok is False
    assert "threshold_max_llm_calls" in res.failures

