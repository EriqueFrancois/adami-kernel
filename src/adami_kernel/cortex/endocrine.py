"""Discrete endocrine-style load status derived from limiter + task queue."""

from __future__ import annotations

from typing import Any

# Stable tokens for prompts / diagnostics (not user-facing copy).
STATUS_CALM = "calm"
STATUS_NORMAL = "normal"
STATUS_STRESSED = "stressed"
STATUS_OVERLOADED = "overloaded"


def status_or_normal(endocrine: Any) -> str:
    if endocrine is None:
        return STATUS_NORMAL
    fn = getattr(endocrine, "status", None)
    if not callable(fn):
        return STATUS_NORMAL
    try:
        return str(fn() or STATUS_NORMAL)
    except Exception:
        return STATUS_NORMAL


class EndocrineSystem:
    """Maps concurrency pressure to a small status vocabulary."""

    def __init__(self, limiter: Any = None, task_queue: Any = None) -> None:
        self._limiter = limiter
        self._task_queue = task_queue

    def set_task_queue(self, task_queue: Any) -> None:
        self._task_queue = task_queue

    def set_limiter(self, limiter: Any) -> None:
        self._limiter = limiter

    def status(self) -> str:
        pending = 0
        tq = self._task_queue
        if tq is not None:
            try:
                if hasattr(tq, "_total_pending"):
                    pending = int(tq._total_pending())
                else:
                    pending = 0
            except Exception:
                pending = 0

        token_ratio = 1.0
        lim = self._limiter
        if lim is not None:
            try:
                cap = float(getattr(lim, "capacity", 0) or 0)
                tok = float(getattr(lim, "tokens", cap) or 0)
                if cap > 0:
                    token_ratio = max(0.0, min(1.0, tok / cap))
            except Exception:
                token_ratio = 1.0

        if pending >= 10 or token_ratio < 0.2:
            return STATUS_OVERLOADED
        if pending >= 3 or token_ratio < 0.5:
            return STATUS_STRESSED
        if pending == 0 and token_ratio > 0.8:
            return STATUS_CALM
        return STATUS_NORMAL
