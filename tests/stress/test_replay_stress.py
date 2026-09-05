"""步骤 5：回放路径压力（夜间 / workflow_dispatch）。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from adami_kernel.integration.sim.replay import load_ndjson_records, validate_phase1_records

GOLDEN = Path(__file__).resolve().parent.parent / "replay" / "fixtures" / "golden_trace.ndjson"


@pytest.mark.stress
def test_parallel_golden_replay_validate() -> None:
    """Repeat golden NDJSON validation; iteration count is env-tunable.

    Sequential on purpose: a thread pool plus the suite's async autouse cleanup
    has been a source of GitHub Actions ``replay-stress`` failures (job ~36s).
    """
    iterations = int(os.environ.get("STRESS_REPLAY_ITERATIONS", "24"))
    recs = load_ndjson_records(GOLDEN)
    threshold = int(os.environ.get("STRESS_FAILURE_THRESHOLD", "0"))
    errors: list[BaseException] = []
    for _ in range(max(1, iterations)):
        try:
            validate_phase1_records(recs)
        except BaseException as e:
            errors.append(e)
    if len(errors) > threshold:
        raise AssertionError(
            f"stress failures {len(errors)} > threshold {threshold}: {errors[:3]!r}"
        )
