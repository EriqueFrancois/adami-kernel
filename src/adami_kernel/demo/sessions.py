"""In-memory demo sessions. Never persisted."""

from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class DemoSession:
    session_id: str
    locale: str
    csrf_token: str
    created_at: float
    last_seen_at: float
    turns_used: int = 0
    busy_task_id: str | None = None
    messages: list[dict[str, str]] = field(default_factory=list)
    scratchpad: str = ""
    client_turn_ids: dict[str, str] = field(default_factory=dict)

    def expires_at(self, idle_ttl: float, max_ttl: float) -> float:
        return min(self.created_at + max_ttl, self.last_seen_at + idle_ttl)

    def is_expired(self, now: float, idle_ttl: float, max_ttl: float) -> bool:
        return now >= self.expires_at(idle_ttl, max_ttl)

    def turns_remaining(self, max_turns: int) -> int:
        return max(0, int(max_turns) - int(self.turns_used))

    def touch(self, now: float) -> None:
        self.last_seen_at = now

    def append_turn(self, user: str, assistant: str, keep: int = 6) -> None:
        self.messages.append({"role": "user", "content": user})
        self.messages.append({"role": "assistant", "content": assistant})
        max_msgs = keep * 2
        if len(self.messages) > max_msgs:
            self.messages = self.messages[-max_msgs:]


class SessionStore:
    def __init__(self, *, idle_ttl: float, max_ttl: float) -> None:
        self.idle_ttl = idle_ttl
        self.max_ttl = max_ttl
        self._sessions: dict[str, DemoSession] = {}

    def get(self, session_id: str | None) -> DemoSession | None:
        if not session_id:
            return None
        return self._sessions.get(session_id)

    def put(self, session: DemoSession) -> None:
        self._sessions[session.session_id] = session

    def drop(self, session_id: str) -> None:
        self._sessions.pop(session_id, None)

    def count(self) -> int:
        return len(self._sessions)

    def purge_expired(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        dead = [
            sid
            for sid, s in self._sessions.items()
            if s.is_expired(now, self.idle_ttl, self.max_ttl)
        ]
        for sid in dead:
            self._sessions.pop(sid, None)
        return len(dead)
