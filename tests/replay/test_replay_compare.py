from __future__ import annotations

import json
from pathlib import Path

from adami_kernel.integration.sim.replay_compare import compare_suite_reports


def _write(p: Path, obj: dict) -> None:
    p.write_text(json.dumps(obj, ensure_ascii=False) + "\n", encoding="utf-8")


def test_compare_detects_regression_score_drop(tmp_path: Path) -> None:
    base = tmp_path / "base.json"
    head = tmp_path / "head.json"
    _write(
        base,
        {
            "ok": True,
            "score": 100,
            "failures": [],
            "traces": [{"name": "a", "result": {"ok": True, "score": 100, "failures": [], "scorecard": {"correctness": 100, "safety": 100, "ux": 100, "noise": 100}}}],
        },
    )
    _write(
        head,
        {
            "ok": True,
            "score": 99,
            "failures": [],
            "traces": [{"name": "a", "result": {"ok": True, "score": 99, "failures": [], "scorecard": {"correctness": 100, "safety": 100, "ux": 100, "noise": 100}}}],
        },
    )
    summary, md = compare_suite_reports(baseline_json=base, head_json=head)
    assert summary.ok is False
    assert any("suite_score_drop" in r or "trace_score_drop" in r for r in summary.regressions)
    assert "Regressions" in md


def test_compare_allows_score_drop_when_disabled(tmp_path: Path) -> None:
    base = tmp_path / "base.json"
    head = tmp_path / "head.json"
    _write(
        base,
        {
            "ok": True,
            "score": 100,
            "failures": [],
            "traces": [{"name": "a", "result": {"ok": True, "score": 100, "failures": [], "scorecard": {"correctness": 100, "safety": 100, "ux": 100, "noise": 100}}}],
        },
    )
    _write(
        head,
        {
            "ok": True,
            "score": 99,
            "failures": [],
            "traces": [{"name": "a", "result": {"ok": True, "score": 99, "failures": [], "scorecard": {"correctness": 100, "safety": 100, "ux": 100, "noise": 100}}}],
        },
    )
    summary, _ = compare_suite_reports(
        baseline_json=base, head_json=head, fail_on_score_drop=False
    )
    assert summary.ok is True


def test_compare_allows_score_drop_with_threshold(tmp_path: Path) -> None:
    base = tmp_path / "base.json"
    head = tmp_path / "head.json"
    _write(
        base,
        {
            "ok": True,
            "score": 100,
            "failures": [],
            "traces": [
                {
                    "name": "a",
                    "result": {
                        "ok": True,
                        "score": 100,
                        "failures": [],
                        "scorecard": {"correctness": 100, "safety": 100, "ux": 100, "noise": 100},
                    },
                }
            ],
        },
    )
    _write(
        head,
        {
            "ok": True,
            "score": 99,
            "failures": [],
            "traces": [
                {
                    "name": "a",
                    "result": {
                        "ok": True,
                        "score": 99,
                        "failures": [],
                        "scorecard": {"correctness": 100, "safety": 100, "ux": 100, "noise": 100},
                    },
                }
            ],
        },
    )
    summary, _ = compare_suite_reports(baseline_json=base, head_json=head, max_score_drop=1)
    assert summary.ok is True


def test_compare_detects_dim_drop_over_threshold(tmp_path: Path) -> None:
    base = tmp_path / "base.json"
    head = tmp_path / "head.json"
    _write(
        base,
        {
            "ok": True,
            "score": 100,
            "failures": [],
            "traces": [
                {
                    "name": "a",
                    "result": {
                        "ok": True,
                        "score": 100,
                        "failures": [],
                        "scorecard": {"correctness": 100, "safety": 100, "ux": 100, "noise": 100},
                    },
                }
            ],
        },
    )
    _write(
        head,
        {
            "ok": True,
            "score": 99,
            "failures": [],
            "traces": [
                {
                    "name": "a",
                    "result": {
                        "ok": True,
                        "score": 99,
                        "failures": [],
                        "scorecard": {"correctness": 99, "safety": 100, "ux": 100, "noise": 100},
                    },
                }
            ],
        },
    )
    summary, _ = compare_suite_reports(
        baseline_json=base, head_json=head, max_score_drop=1, max_dim_drop=0
    )
    assert summary.ok is False
    assert any("trace_dim_drop:a:correctness" in r for r in summary.regressions)


def test_compare_detects_ok_to_fail(tmp_path: Path) -> None:
    base = tmp_path / "base.json"
    head = tmp_path / "head.json"
    _write(
        base,
        {
            "ok": True,
            "score": 100,
            "failures": [],
            "traces": [{"name": "a", "result": {"ok": True, "score": 100, "failures": [], "scorecard": {"correctness": 100, "safety": 100, "ux": 100, "noise": 100}}}],
        },
    )
    _write(
        head,
        {
            "ok": False,
            "score": 60,
            "failures": ["trace_failed:a"],
            "traces": [{"name": "a", "result": {"ok": False, "score": 60, "failures": ["x"], "scorecard": {"correctness": 0, "safety": 100, "ux": 100, "noise": 100}}}],
        },
    )
    summary, _ = compare_suite_reports(baseline_json=base, head_json=head)
    assert summary.ok is False
    assert any(r.startswith("trace_ok_to_fail:a") for r in summary.regressions)

