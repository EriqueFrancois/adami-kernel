"""Contract tests for WorkflowState.metadata profile_id (Phase 2.6)."""

from __future__ import annotations

from adami_kernel.orchestrator.workflow_models import (
    WorkflowState,
    create_initial_workflow_state,
    ensure_default_profile_id,
)


def test_create_initial_workflow_state_sets_planner_initial() -> None:
    st = create_initial_workflow_state("42", "hello")
    assert st.metadata.get("profile_id") == "planner_initial"


def test_ensure_default_profile_id_respects_existing() -> None:
    st = WorkflowState(chat_id="1", metadata={"profile_id": "custom"})
    ensure_default_profile_id(st, "planner_initial")
    assert st.metadata["profile_id"] == "custom"


def test_ensure_default_profile_id_sets_when_missing() -> None:
    st = WorkflowState(chat_id="1")
    ensure_default_profile_id(st, "multi_agent_orchestrator")
    assert st.metadata["profile_id"] == "multi_agent_orchestrator"
