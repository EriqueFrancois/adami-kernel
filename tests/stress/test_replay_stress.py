"""步骤 5：回放路径压力与轻量抖动（夜间 / workflow_dispatch）。"""

from __future__ import annotations

import os
import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import pytest

from adami_kernel.integration.sim.replay import load_ndjson_records, validate_phase1_records

GOLDEN = Path(__file__).resolve().parent.parent / "replay" / "fixtures" / "golden_trace.ndjson"


def _validate_once(_: int) -> None:
    time.sleep(random.uniform(0.0, 0.03))
    recs = load_ndjson_records(GOLDEN)
    validate_phase1_records(recs)


@pytest.mark.stress
def test_parallel_golden_replay_validate() -> None:
    """多线程重复校验黄金 NDJSON；迭代次数可由环境变量调大。"""
    iterations = int(os.environ.get("STRESS_REPLAY_ITERATIONS", "24"))
    workers = min(8, max(2, iterations // 4))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_validate_once, i) for i in range(iterations)]
        threshold = int(os.environ.get("STRESS_FAILURE_THRESHOLD", "0"))
        errors: list[Exception] = []
        for fut in as_completed(futures):
            try:
                fut.result()
            except BaseException as e:
                errors.append(e)
        if len(errors) > threshold:
            raise AssertionError(
                f"stress failures {len(errors)} > threshold {threshold}: {errors[:3]!r}"
            )
