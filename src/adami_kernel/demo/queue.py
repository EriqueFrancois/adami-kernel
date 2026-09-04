"""Bounded wait queue for demonstration turns."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field


@dataclass
class Waiter:
    task_id: str
    session_id: str
    enqueued_at: float
    claimed: asyncio.Event = field(default_factory=asyncio.Event)
    cancelled: asyncio.Event = field(default_factory=asyncio.Event)


class WaitQueue:
    def __init__(self, maxsize: int) -> None:
        self.maxsize = maxsize
        self._items: list[Waiter] = []

    def __len__(self) -> int:
        return len(self._items)

    def try_enqueue(self, waiter: Waiter) -> int | None:
        if len(self._items) >= self.maxsize:
            return None
        self._items.append(waiter)
        return len(self._items)

    def remove(self, task_id: str) -> Waiter | None:
        for i, w in enumerate(self._items):
            if w.task_id == task_id:
                return self._items.pop(i)
        return None

    def position(self, task_id: str) -> int | None:
        for i, w in enumerate(self._items):
            if w.task_id == task_id:
                return i + 1
        return None

    def pop_next(self) -> Waiter | None:
        if not self._items:
            return None
        return self._items.pop(0)
