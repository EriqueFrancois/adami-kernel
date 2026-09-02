"""Bounded curiosity queue for MetaCortex genome-plan follow-ups."""

from __future__ import annotations

from collections import deque
from typing import Deque, List, Optional

from adami_kernel.config import settings


class CuriosityQueue:
    """In-memory FIFO of curiosity items (long-goal strings)."""

    def __init__(self, max_items: Optional[int] = None) -> None:
        cap = int(max_items if max_items is not None else getattr(settings, "ADAMI_CURIOSITY_QUEUE_MAX", 64))
        self._max = max(1, cap)
        self._items: Deque[str] = deque(maxlen=self._max)

    def add_curiosity(self, text: str) -> None:
        s = str(text or "").strip()
        if not s:
            return
        self._items.append(s)

    def pop(self) -> Optional[str]:
        if not self._items:
            return None
        return self._items.popleft()

    def peek(self) -> Optional[str]:
        if not self._items:
            return None
        return self._items[0]

    def list(self) -> List[str]:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)
