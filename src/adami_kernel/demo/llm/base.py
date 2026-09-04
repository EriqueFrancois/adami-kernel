"""LLM provider protocol."""

from __future__ import annotations

from typing import Protocol


class DemoLLM(Protocol):
    async def complete(self, *, prompt: str, max_tokens: int, timeout_sec: float) -> str: ...
