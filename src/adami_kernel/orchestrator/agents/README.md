## Purpose

Role-based agents used by orchestration flows (both DAG and multi-agent paths). Agents typically produce structured payloads consumed by the Planner / WorkflowEngine pipeline.

## Key files

- `researcher.py`: research / requirements clarification and context building.
- `engineer.py`: generates/refines skill code; integrates skill naming and validation flows.
- `executor.py`: executes skills or build steps; reports execution results.
- `critic.py`: quality gate / review feedback (approve/reject).
- `human.py`: HITL placeholder (may be optional / import-guarded).
- `reflection_agent.py`: reflection helper agent.

## Operational notes

- Agents should communicate via structured dictionaries to keep CLI/Web formatting stable.

