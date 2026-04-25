## Purpose

This directory contains the **Python kernel package** (`adami_kernel`). It owns runtime orchestration, memory, skills, and the Web Console backend. It is designed around **event-driven execution** and a **unified DAG workflow engine**.

This package should not contain runtime-generated artifacts (those belong under `.adami_data/`).

## Key files

- `kernel.py`: kernel process entrypoint (Poetry script: `adami`).
- `config.py`: configuration via `pydantic-settings` (env-driven).
- `monitor.py`: lightweight monitoring / diagnostics helpers.

## Key subdirectories

- `core/`: boot + lifecycle composition and dependency wiring.
- `nexus/`: EventBus, events, nerves (Telegram/Discord), interactive shell.
- `cortex/`: routing/decision logic (LLM router, intent router, decision processor).
- `orchestrator/`: Planner, SkillComposer, WorkflowEngine, multi-agent components.
- `skill_manager/`: skill build/validate/load/versioning, vector store integration.
- `hippocampus/`: LayeredMemory + episodic/subconscious memory systems.
- `web/`: Web Console backend (FastAPI/ASGI-style app + routes + OTEL glue).
- `market/`: skill market ingestion/recommendation (GitHub hunting, etc.).
- `guardian/`: “immune system”/RBAC/limits/sensitive filtering.
- `observability/`: cross-cutting observability shims (e.g. Agent Lightning compat).
- `peripheral/`: external integrations / peripheral modules.
- `self_test/`: self-test / TDD/self-check components.

## Primary flows

- **CLI request execution**
  - `nexus/shell.py` → publish `system.events`
  - `core/lifecycle_manager.py` → bounded consumption
  - `cortex/decision_processor.py` → intent routing + delegation to Planner

- **Composed workflows / skill creation**
  - `orchestrator/planner.py` → `SkillComposer.compose_workflow(...)`
  - publish `workflow.events` `WORKFLOW_START`
  - `orchestrator/workflow_engine.py` executes and persists state via `hippocampus/layered_memory.py`

## Operational notes

- **Logs**: `.adami_data/kernel.log`
- **Persistent memory DB**: `.adami_data/l2_memory.db`

