## Purpose

`orchestrator/` owns **planning and execution** for complex tasks:

- the Planner control flow
- SkillComposer DAG construction
- WorkflowEngine (event-driven DAG state machine)
- multi-agent orchestration (fallback / specialized flows)
- self-reflection loop and TDD evolution

## Key files

- `planner.py`: main planning loop; integrates SkillRouter/SkillComposer; publishes `WORKFLOW_START`.
- `workflow_engine.py`: executes `WorkflowState` DAGs via `workflow.events` and persists state.
- `workflow_models.py`: `WorkflowState`, `Node`, and event payload shapes.
- `long_task_schema.py`: module 4 long-horizon **phase** + `StageArtifact` schema; controlled `context` keys (`current_phase`, `long_task_stages`); see `maybe_initialize_long_task_context` (called from `workflow_engine.prepare_composed_workflow_for_bus` when tracking is enabled).
- `long_task_checkpoint.py`: logical namespace `checkpoint/v1/wf/{workflow_id}/ph/{phase}` implemented via `LayeredMemory.save_workflow_phase_checkpoint` / `get_workflow_phase_checkpoint_record`, `get_last_good_checkpoint`, `record_checkpoint_failure`; use `save_phase_checkpoint_with_retry` for contention. Legacy `checkpoint_{domain}` rows are still readable via `get_workflow_checkpoint`.
- `long_task_phase_gate.py` (step 3): `emit_phase_transition_if_changed`, `checkpoint_hitl_boundary`; wired in `workflow_engine._route_next` (DAG), HITL pre-pause / post-resume, and `multi_agent_orchestrator._orchestrate` (role handoff). Publishes `workflow.events` with `payload.event_type == "PHASE_TRANSITION"`; `WorkflowState.history` entries use `event_type: "phase_transition"` for offline replay.
- `long_task_failure_policy.py` / `long_task_recovery.py` (step 4): `classify_workflow_node_failure` (transient vs phase_fatal); `_handle_node_failure` uses `error_retry_counts` for transient, `rollback_to_last_good_checkpoint` + `metadata.phase_recovery_count` cap for phase_fatal; audit rows `event_type: workflow_node_failure`. Step 4.1: `resume_workflow` accepts `resume_mode=replay_from_phase` + `replay_phase`; `HitlHandler.process_resume` action `replay`. Config: `ADAMI_LONG_TASK_*_SUBSTRINGS`, `ADAMI_WORKFLOW_PHASE_RECOVERY_MAX`.
- `long_task_sandbox.py` (step 5): `SandboxRunHandle`, `run_isolated_tool_command` (per-run dir under `settings.path_long_task_runs_dir`); `workflow_engine` TOOL nodes use it when long-task tracking is on and `ADAMI_LONG_TASK_ISOLATED_TOOL_RUN` (opt-out per node: `long_task_disable_isolated_run`). Appends `StageArtifact` (`artifact_type=sandbox_run`, `file://` artifacts dir). Existing `ToolboxManager.sandbox_dir` (`.adami_sandbox`) unchanged for non-tracked TOOL runs.
- Step 6 (DeerFlow sidecar): `integration/deer_flow_bridge.py` — optional HTTP/CLI bridge; workflow node type `DELEGATE_DEERFLOW` only when `ADAMI_DEERFLOW_ENABLED`; `prepare_composed_workflow_for_bus` rejects delegate nodes if disabled. Security: `docs/deer_flow_bridge_security.md`.
- Step 7 (observability): Sim `ReplayTraceRecordV1` + `event_to_record` carry `phase` / `checkpoint_seq` for `PHASE_TRANSITION`; phase gate publishes them on the bus and in `history`; experience sink `record_phase_transition`. See `docs/module4_observability_acceptance.md`, `scripts/module4_trace_summary.py`, `tests/test_long_task_phases.py`.
- `skill_composer.py`: composes workflows (including `CREATE_NEW_SKILL` specialized DAG).
- `multi_agent_orchestrator.py`: legacy/multi-agent execution path (fallback/optional).
- `reflexion_loop.py`: self-healing loop (retry/modify/skip nodes).
- `tdd_evolution.py`: TDD-based skill evolution pipeline.
- `hitl_handler.py`: human-in-the-loop pauses/resumes (high risk nodes).
- `multi_tenant_guard.py`: chat isolation / locks.

## Key subdirectories

- `agents/`: role agents (Researcher/Engineer/Executor/Critic/Human).

## Primary flows

- **Skill creation (event-driven DAG)**
  - `planner.py` → `skill_composer.compose_workflow(...)`
  - `workflow_engine.prepare_composed_workflow_for_bus(...)`
  - publish `workflow.events: WORKFLOW_START`
  - `workflow_engine.py` runs nodes and persists `workflow_state_*`

