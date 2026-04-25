"""2.1 断言模型与故意损坏检测。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from adami_kernel.integration.sim.replay import (
    TraceAssertion,
    apply_assertions,
    assert_record_matches,
    load_ndjson_records,
    trace_assertion_from_mapping,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_trace_assertion_from_mapping() -> None:
    a = trace_assertion_from_mapping(
        {
            "expect_topic": "system.events",
            "expect_payload_keys": ["task", "platform"],
            "forbid_string": "sk-",
        }
    )
    assert a.expect_topic == "system.events"
    assert a.expect_payload_keys == frozenset({"task", "platform"})
    assert a.forbid_string == "sk-"


def test_apply_assertions_golden() -> None:
    recs = load_ndjson_records(FIXTURES / "golden_trace.ndjson")
    apply_assertions(
        recs,
        [
            (
                0,
                TraceAssertion(
                    expect_topic="system.events",
                    expect_payload_keys=frozenset({"task", "platform"}),
                ),
            ),
            (2, TraceAssertion(expect_payload_keys=frozenset({"kind"}))),
        ],
    )


def test_assertion_fails_when_payload_key_removed(tmp_path) -> None:
    """故意改坏一行 payload：去掉 task，带 expect_payload_keys 时应失败。"""
    raw_path = FIXTURES / "golden_trace.ndjson"
    lines = [ln for ln in raw_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
    obj = json.loads(lines[0])
    del obj["payload_redacted"]["task"]
    bad = tmp_path / "corrupt.ndjson"
    bad.write_text(json.dumps(obj, ensure_ascii=False) + "\n", encoding="utf-8")
    recs = load_ndjson_records(bad)
    with pytest.raises(AssertionError, match="missing keys"):
        assert_record_matches(
            recs[0],
            TraceAssertion(expect_payload_keys=frozenset({"task", "platform"})),
        )


def test_forbid_string_detects_secret_like(tmp_path) -> None:
    p = tmp_path / "leak.ndjson"
    p.write_text(
        '{"schema_version":"adami_replay_trace.v1","ts":1,"trace_id":"x","source_module":"m","target_topic":"t",'
        '"payload_redacted":{"note":"sk-abcdefghijklmnopqrstuvwxyz123456"}}\n',
        encoding="utf-8",
    )
    recs = load_ndjson_records(p)
    with pytest.raises(AssertionError, match="forbid_string"):
        assert_record_matches(recs[0], TraceAssertion(forbid_string="sk-"))
