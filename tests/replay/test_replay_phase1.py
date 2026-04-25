"""阶段 1：NDJSON 只读校验。"""

from __future__ import annotations

from pathlib import Path

import pytest

from adami_kernel.integration.sim.replay import (
    ReplayValidationError,
    load_ndjson_records,
    validate_phase1_records,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_load_golden_trace() -> None:
    recs = load_ndjson_records(FIXTURES / "golden_trace.ndjson")
    assert len(recs) == 3
    assert recs[0].trace_id == "golden-1"


def test_validate_phase1_golden_ok() -> None:
    recs = load_ndjson_records(FIXTURES / "golden_trace.ndjson")
    validate_phase1_records(recs)


def test_validate_rejects_bad_schema_version(tmp_path) -> None:
    p = tmp_path / "bad.ndjson"
    p.write_text(
        '{"schema_version":"wrong","ts":1,"trace_id":"a","source_module":"m","target_topic":"t",'
        '"payload_redacted":{}}\n',
        encoding="utf-8",
    )
    recs = load_ndjson_records(p)
    with pytest.raises(ReplayValidationError, match="schema_version"):
        validate_phase1_records(recs)


def test_validate_rejects_non_monotonic_ts(tmp_path) -> None:
    p = tmp_path / "order.ndjson"
    p.write_text(
        '{"schema_version":"adami_replay_trace.v1","ts":2,"trace_id":"a","source_module":"m","target_topic":"t",'
        '"payload_redacted":{}}\n'
        '{"schema_version":"adami_replay_trace.v1","ts":1,"trace_id":"b","source_module":"m","target_topic":"t",'
        '"payload_redacted":{}}\n',
        encoding="utf-8",
    )
    recs = load_ndjson_records(p)
    with pytest.raises(ReplayValidationError, match="monotonic"):
        validate_phase1_records(recs)
