"""In-memory rate limits (per identity hash and per session)."""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(
        self,
        *,
        ip_per_minute: int,
        ip_per_day: int,
        session_per_minute: int,
    ) -> None:
        self.ip_per_minute = ip_per_minute
        self.ip_per_day = ip_per_day
        self.session_per_minute = session_per_minute
        self._ip_min: dict[str, deque[float]] = defaultdict(deque)
        self._ip_day: dict[str, deque[float]] = defaultdict(deque)
        self._sess_min: dict[str, deque[float]] = defaultdict(deque)
        self.rejects = 0

    def _prune(self, q: deque[float], now: float, window: float) -> None:
        while q and now - q[0] > window:
            q.popleft()

    def allow_ip(self, identity: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        mq = self._ip_min[identity]
        dq = self._ip_day[identity]
        self._prune(mq, now, 60.0)
        self._prune(dq, now, 86400.0)
        if len(mq) >= self.ip_per_minute or len(dq) >= self.ip_per_day:
            self.rejects += 1
            return False
        mq.append(now)
        dq.append(now)
        return True

    def allow_session(self, session_id: str, now: float | None = None) -> bool:
        now = time.time() if now is None else now
        q = self._sess_min[session_id]
        self._prune(q, now, 60.0)
        if len(q) >= self.session_per_minute:
            self.rejects += 1
            return False
        q.append(now)
        return True
