"""Lightweight in-process metrics. No user content."""

from __future__ import annotations

import time
from collections import deque


class DemoMetrics:
    def __init__(self) -> None:
        self.requests = 0
        self.errors = 0
        self.llm_calls = 0
        self.estimated_output_tokens = 0
        self._durations: deque[float] = deque(maxlen=200)
        self.started_at = time.time()

    def record_duration(self, sec: float) -> None:
        self._durations.append(float(sec))

    def snapshot(self, *, sessions: int, running: int, queued: int, rate_rejects: int) -> dict[str, object]:
        durs = sorted(self._durations)
        p50 = durs[len(durs) // 2] if durs else 0.0
        p95 = durs[int(len(durs) * 0.95)] if durs else 0.0
        avg = (sum(durs) / len(durs)) if durs else 0.0
        return {
            "sessions": sessions,
            "runningTasks": running,
            "queueLength": queued,
            "requests": self.requests,
            "rateLimited": rate_rejects,
            "errors": self.errors,
            "taskDurationSec": {"avg": round(avg, 3), "p50": round(p50, 3), "p95": round(p95, 3)},
            "llmCalls": self.llm_calls,
            "estimatedOutputTokens": self.estimated_output_tokens,
        }
