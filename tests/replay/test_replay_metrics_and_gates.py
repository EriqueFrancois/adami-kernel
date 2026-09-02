from __future__ import annotations

from pathlib import Path

from adami_kernel.integration.sim.replay import load_ndjson_records
from adami_kernel.integration.sim.replay_eval import (
    _extract_perf_metrics,
    evaluate_trace_file,
)


def test_extract_perf_metrics_counts_tool_and_llm_calls() -> None:
    # Use a real golden trace that contains both tool + llm lifecycle events.
    recs = load_ndjson_records("docs/evals/traces/workflow_engine/golden_trace.ndjson")
    tool_calls, tool_lat, llm_calls, llm_lat = _extract_perf_metrics(recs)
    assert tool_calls == 1
    assert tool_lat >= 0
    assert llm_calls == 0
    assert llm_lat == 0

    recs2 = load_ndjson_records("docs/evals/traces/llm_call/golden_trace.ndjson")
    tool_calls2, tool_lat2, llm_calls2, llm_lat2 = _extract_perf_metrics(recs2)
    assert tool_calls2 == 0
    assert tool_lat2 == 0
    assert llm_calls2 == 1
    assert llm_lat2 >= 0


def test_scorecard_max_tool_latency_gate(tmp_path: Path) -> None:
    # workflow_engine has tool_latency_ms_total > 0 (echo), so setting max=0 should fail.
    trace = Path("docs/evals/traces/workflow_engine/golden_trace.ndjson")
    scorecard = tmp_path / "scorecard.json"
    scorecard.write_text('{"max_tool_latency_ms_total": 0}\n', encoding="utf-8")

    res = evaluate_trace_file(
        trace_file=trace,
        assertions_file=Path("docs/evals/traces/workflow_engine/assertions.json"),
        scorecard_file=scorecard,
    )
    assert res.ok is False
    assert "threshold_max_tool_latency_ms_total" in res.failures


def test_scorecard_operability_gate_missing_tool_field(tmp_path: Path) -> None:
    # A TOOL_CALL_* without tool field should fail when operability is gated + template rule requires tool field.
    trace = tmp_path / "trace.ndjson"
    trace.write_text(
        "\n".join(
            [
                '{"schema_version":"adami_replay_trace.v1","ts":1,"trace_id":"t1","source_module":"user.prompt","target_topic":"system.events","payload_redacted":{"task":"/x","chat_id":"cli","platform":"cli"}}',
                '{"schema_version":"adami_replay_trace.v1","ts":2,"trace_id":"t1","source_module":"cortex.tools_manager","target_topic":"system.events","payload_redacted":{"event_type":"TOOL_CALL_START"}}',
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    scorecard = tmp_path / "scorecard.json"
    scorecard.write_text('{"min_operability": 100}\n', encoding="utf-8")
    res = evaluate_trace_file(trace_file=trace, scorecard_file=scorecard)
    assert res.ok is False
    assert "threshold_operability" in res.failures

