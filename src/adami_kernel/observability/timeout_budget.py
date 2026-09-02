from __future__ import annotations

import asyncio
from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Optional


class BudgetExceededError(RuntimeError):
    """Raised when the current task has no remaining timeout budget."""


@dataclass(frozen=True)
class TaskTimeoutBudget:
    trace_id: str
    deadline_monotonic: float


_task_timeout_budget_ctx: ContextVar[Optional[TaskTimeoutBudget]] = ContextVar(
    "adami_task_timeout_budget", default=None
)


def set_task_timeout_budget(trace_id: str, *, timeout_sec: float) -> Token[Optional[TaskTimeoutBudget]]:
    """Bind a timeout budget to the current async context."""
    now = asyncio.get_event_loop().time()
    deadline = now + max(0.0, float(timeout_sec))
    return _task_timeout_budget_ctx.set(
        TaskTimeoutBudget(trace_id=str(trace_id), deadline_monotonic=float(deadline))
    )


def reset_task_timeout_budget(token: Token[Optional[TaskTimeoutBudget]]) -> None:
    _task_timeout_budget_ctx.reset(token)


def get_task_timeout_budget() -> Optional[TaskTimeoutBudget]:
    return _task_timeout_budget_ctx.get()


def remaining_task_budget_sec(*, floor_sec: float = 0.0) -> Optional[float]:
    """Return remaining seconds, or None if no budget is bound."""
    b = _task_timeout_budget_ctx.get()
    if b is None:
        return None
    now = asyncio.get_event_loop().time()
    rem = float(b.deadline_monotonic - now)
    if rem < float(floor_sec):
        rem = float(floor_sec)
    return rem


def clamp_timeout_to_budget(timeout_sec: Optional[float], *, min_remaining_sec: float = 0.2) -> Optional[float]:
    """Clamp a proposed timeout to the remaining task budget (if any).

    If the remaining budget is below ``min_remaining_sec``, raises BudgetExceededError.
    """
    rem = remaining_task_budget_sec()
    if rem is None:
        return float(timeout_sec) if timeout_sec is not None else None
    if rem < float(min_remaining_sec):
        raise BudgetExceededError("task timeout budget exceeded")
    if timeout_sec is None:
        return float(rem)
    try:
        t = float(timeout_sec)
    except Exception:
        return float(rem)
    return float(min(t, rem))

