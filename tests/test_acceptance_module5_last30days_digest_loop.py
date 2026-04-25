from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, List
from unittest.mock import AsyncMock, MagicMock

import pytest

from adami_kernel.orchestrator.planner import TaskPlanner


class _FakeBus:
    def __init__(self) -> None:
        self.events: List[Any] = []

    async def publish(self, event: Any) -> None:
        self.events.append(event)


class _FakeMemory:
    def __init__(self) -> None:
        self.saved = []

    async def save_workflow_state(self, state: Any) -> None:
        self.saved.append(state)


@pytest.mark.asyncio
async def test_last30days_success_schedules_digest_task(tmp_path: Path) -> None:
    # Prepare a fake note file that "LAST30DAYS_DIGEST" would have written.
    brain = tmp_path / "brain"
    inbox = brain / "Inbox"
    inbox.mkdir(parents=True)
    note = inbox / "last30days-note.md"
    note.write_text("# T\n\nhello world\n", encoding="utf-8")

    bus = _FakeBus()
    memory = _FakeMemory()

    evo = MagicMock()
    evo.get_skill = MagicMock(return_value=AsyncMock())
    evo.execute_tool_dispatch = AsyncMock(
        return_value={
            "ok": True,
            "note_path": str(note),
            "summary": "hello",
            "cache_hit": False,
            "sources_mode": "auto",
            "error": None,
        }
    )

    # SkillRouter returns a call spec for LAST30DAYS_DIGEST so planner calls execute_tool_dispatch.
    skill_router = MagicMock()
    skill_router.get_call_spec = AsyncMock(
        return_value=SimpleNamespace(skill_name="LAST30DAYS_DIGEST", args={"topic": "x"})
    )

    planner = TaskPlanner(
        router=MagicMock(call_llm=AsyncMock(return_value="ok")),
        evolution_engine=evo,
        bus=bus,
        sensitive_filter=MagicMock(),
        episodic_memory=None,
        memory=memory,
        workflow_engine=None,
        multi_agent_orchestrator=None,
        reflexion_loop=None,
        tdd_evolution=None,
        skill_composer=None,
        skill_router=skill_router,
        second_brain=None,
    )

    # Execute one iteration, triggering last30days tool call + digest scheduling.
    out = await planner._execute_single_iteration("run last30days", "tr1", "42", {})
    assert isinstance(out, dict) and out.get("ok") is True

    # Verify a follow-up digest event was published to system.events.
    digest_events = [
        e for e in bus.events if str(getattr(e, "trace_id", "")).endswith("_digest_note")
    ]
    assert digest_events, "expected a digest follow-up event"
    ev = digest_events[0]
    assert ev.target_topic == "system.events"
    assert ev.payload.get("chat_id") == "42"
    task = str(ev.payload.get("task") or "")
    assert "digest this note" in task
    assert str(note) in task

    # Verify a workflow state was saved with an artifact anchor (best-effort).
    assert memory.saved, "expected save_workflow_state to be called"
    saved = memory.saved[0]
    ctx = getattr(saved, "context", {}) or {}
    stages = ctx.get("long_task_stages") or []
    assert isinstance(stages, list)
    assert stages, "expected at least one StageArtifact in context"
