"""Readonly demo executor. No DecisionProcessor, Toolbox, or HybridLLMRouter."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

from adami_kernel.demo.messages import error_message
from adami_kernel.demo.models import DENIED_TOOL_MARKERS
from adami_kernel.demo.sessions import DemoSession
from adami_kernel.demo.sse import chunk_text
from adami_kernel.demo.tools import find_denied_marker, is_allowed_tool

_SCENARIO_TOOL = {
    "what-adami-can-do": "explain_capability",
    "goal-planning": "plan_outline",
    "analyze-problem": "organize_notes",
    "memory-mechanism": "scratchpad_write",
    "reflect-improve": "reflect",
    "readonly-organize": "organize_notes",
    "freeform": "explain_capability",
}


def _prompt(session: DemoSession, scenario_id: str, message: str, max_chars: int = 4000) -> str:
    history = "\n".join(f"{m['role']}: {m['content']}" for m in session.messages[-12:])
    scratch = session.scratchpad[:2000]
    text = (
        "You are the Adami guided demo. Stay inside a readonly capability demo. "
        "Never claim to run shell, SSH, git, messengers, training, evolution, or web search.\n"
        f"scenario={scenario_id}\nscratchpad={scratch}\nhistory={history}\nuser={message}\n"
    )
    return text[: max(200, int(max_chars))]


async def execute_turn(
    *,
    llm: Any,
    session: DemoSession,
    scenario_id: str,
    message: str,
    max_tokens: int,
    timeout_sec: float,
    cancel_event: Any,
    max_prompt_chars: int = 4000,
) -> AsyncIterator[tuple[str, dict[str, Any]]]:
    locale = session.locale
    if find_denied_marker(message):
        yield (
            "error",
            {"code": "tool_denied", "message": error_message(locale, "tool_denied")},
        )
        return

    yield ("status", {"phase": "analyzing"})
    tool_name = _SCENARIO_TOOL.get(scenario_id, "explain_capability")
    if not is_allowed_tool(tool_name):
        yield (
            "error",
            {"code": "tool_denied", "message": error_message(locale, "tool_denied")},
        )
        return

    if scenario_id == "memory-mechanism":
        session.scratchpad = (session.scratchpad + "\n" + message).strip()[-8000:]
        yield (
            "tool",
            {
                "name": "scratchpad_write",
                "readonly": True,
                "summary": "Updated the temporary in-memory scratchpad for this session.",
            },
        )
        yield (
            "tool",
            {
                "name": "scratchpad_read",
                "readonly": True,
                "summary": "Read the temporary scratchpad (session memory only).",
            },
        )
    else:
        yield (
            "tool",
            {
                "name": tool_name,
                "readonly": True,
                "summary": "Readonly demonstration action; no external side effects.",
            },
        )

    yield ("status", {"phase": "organizing"})
    if cancel_event.is_set():
        return
    try:
        text = await llm.complete(
            prompt=_prompt(session, scenario_id, message, max_chars=max_prompt_chars),
            max_tokens=max_tokens,
            timeout_sec=timeout_sec,
        )
    except Exception:
        yield (
            "error",
            {"code": "unavailable", "message": error_message(locale, "model_failed")},
        )
        return
    if cancel_event.is_set():
        return
    if find_denied_marker(text) or any(m in text.lower() for m in DENIED_TOOL_MARKERS):
        yield (
            "error",
            {"code": "tool_denied", "message": error_message(locale, "tool_denied")},
        )
        return

    yield ("status", {"phase": "answering"})
    for part in chunk_text(text, 40):
        if cancel_event.is_set():
            return
        yield ("delta", {"text": part})
    session.append_turn(message, text, keep=6)
    yield ("assistant_text", {"text": text})
