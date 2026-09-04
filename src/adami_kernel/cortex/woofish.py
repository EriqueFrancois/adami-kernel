"""Short-horizon workload / timeout-risk snapshot (diagnostics name: WoofishPredictor)."""

from __future__ import annotations

import statistics
import time
from collections import deque
from typing import Any, Deque, Dict, List

from adami_kernel.config import settings


class WoofishPredictor:
    """Estimates queue wait and timeout risk from queue ages and recent latencies."""

    def __init__(self, task_queue: Any = None) -> None:
        self._task_queue = task_queue
        self._latencies_ms: Deque[float] = deque(maxlen=64)

    def set_task_queue(self, task_queue: Any) -> None:
        self._task_queue = task_queue

    def note_latency_ms(self, latency_ms: float) -> None:
        try:
            v = float(latency_ms)
        except (TypeError, ValueError):
            return
        if v >= 0:
            self._latencies_ms.append(v)

    def snapshot(self) -> Dict[str, Any]:
        now = time.time()
        ages: List[float] = []
        tq = self._task_queue
        if tq is not None:
            try:
                queues = getattr(tq, "_queues", {}) or {}
                for items in queues.values():
                    for it in items or []:
                        created = float(getattr(it, "created_at", now) or now)
                        ages.append(max(0.0, now - created))
            except Exception:
                ages = []

        p50 = float(statistics.median(ages)) if ages else 0.0
        hard = float(getattr(settings, "ADAMI_TASK_HARD_TIMEOUT_SEC", 900.0) or 900.0)
        timeout_risk = 0.0 if hard <= 0 else min(1.0, p50 / hard)

        lat_p50 = 0.0
        if self._latencies_ms:
            lat_p50 = float(statistics.median(self._latencies_ms))

        max_conc = max(1, int(getattr(settings, "ADAMI_EVENT_CONSUMER_MAX_CONCURRENT", 1) or 1))
        recommended = 1 if timeout_risk >= 0.5 else max_conc

        return {
            "queue_wait_p50_sec": round(p50, 3),
            "timeout_risk": round(timeout_risk, 4),
            "llm_tool_latency_p50_ms": round(lat_p50, 3),
            "recommended_concurrency": int(recommended),
            "pending_samples": len(ages),
        }
