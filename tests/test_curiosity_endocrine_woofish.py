"""Curiosity queue, endocrine status, woofish snapshot."""

from __future__ import annotations

from types import SimpleNamespace

from adami_kernel.cortex.curiosity_queue import CuriosityQueue
from adami_kernel.cortex.endocrine import (
    STATUS_CALM,
    STATUS_NORMAL,
    STATUS_OVERLOADED,
    STATUS_STRESSED,
    EndocrineSystem,
)
from adami_kernel.cortex.woofish import WoofishPredictor
from adami_kernel.guardian.limiter import TokenBucketLimiter


def test_curiosity_queue_bound_and_fifo() -> None:
    q = CuriosityQueue(max_items=2)
    q.add_curiosity("a")
    q.add_curiosity("b")
    q.add_curiosity("c")
    assert q.list() == ["b", "c"]
    assert q.peek() == "b"
    assert q.pop() == "b"
    assert q.pop() == "c"
    assert q.pop() is None


def test_endocrine_status_from_limiter_and_queue() -> None:
    lim = TokenBucketLimiter(capacity=10, fill_rate=10.0)
    lim.tokens = 10.0
    tq = SimpleNamespace(_total_pending=lambda: 0)
    endo = EndocrineSystem(limiter=lim, task_queue=tq)
    assert endo.status() == STATUS_CALM

    tq2 = SimpleNamespace(_total_pending=lambda: 4)
    endo.set_task_queue(tq2)
    assert endo.status() == STATUS_STRESSED

    tq3 = SimpleNamespace(_total_pending=lambda: 12)
    endo.set_task_queue(tq3)
    assert endo.status() == STATUS_OVERLOADED

    lim.tokens = 1.0
    endo.set_task_queue(tq)
    assert endo.status() == STATUS_OVERLOADED

    lim.tokens = 4.0
    endo.set_task_queue(tq)
    assert endo.status() == STATUS_STRESSED

    lim.tokens = 7.0
    endo.set_task_queue(SimpleNamespace(_total_pending=lambda: 1))
    assert endo.status() == STATUS_NORMAL


def test_woofish_snapshot_keys_and_latency() -> None:
    item = SimpleNamespace(created_at=0.0)
    tq = SimpleNamespace(_queues={"c1": [item]})
    w = WoofishPredictor(task_queue=tq)
    w.note_latency_ms(100.0)
    snap = w.snapshot()
    assert set(snap) >= {
        "queue_wait_p50_sec",
        "timeout_risk",
        "llm_tool_latency_p50_ms",
        "recommended_concurrency",
        "pending_samples",
    }
    assert snap["pending_samples"] == 1
    assert snap["llm_tool_latency_p50_ms"] == 100.0
