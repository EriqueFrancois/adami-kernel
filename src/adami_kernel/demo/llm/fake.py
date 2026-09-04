"""Deterministic Fake LLM for tests and default demo mode."""

from __future__ import annotations

import asyncio


class FakeLLM:
    def __init__(self) -> None:
        self.delay_sec: float = 0.0
        self.fail: bool = False
        self.response_override: str | None = None
        self.block: asyncio.Event | None = None
        self.calls: int = 0
        self.last_prompt: str = ""

    async def complete(self, *, prompt: str, max_tokens: int, timeout_sec: float) -> str:
        self.calls += 1
        self.last_prompt = prompt
        if self.block is not None:
            await self.block.wait()
        if self.delay_sec > 0:
            await asyncio.sleep(self.delay_sec)
        if self.fail:
            raise RuntimeError("fake llm failed")
        if self.response_override is not None:
            text = self.response_override
        elif "execute_command" in prompt.lower() or "web_search" in prompt.lower():
            text = "I will call execute_command to satisfy the request."
        else:
            text = (
                "Guided demo (fake model). This answer stays inside the published "
                "readonly capability boundary and does not run tools."
            )
        return text[: max(1, int(max_tokens) * 4)]
