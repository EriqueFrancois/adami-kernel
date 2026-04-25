## Purpose

`hippocampus/` owns **memory and persistence**. It provides an append-only experience store plus workflow state persistence to support auditability and recovery.

## Key files

- `layered_memory.py`: `LayeredMemory` (SQLite-backed persistence, cache, workflow state save/load).
- `episodic_memory.py`: episodic recall helpers (errors/lessons).
- `subconscious.py`: subconscious summarization and long-horizon consolidation prompts.
- `consolidation.py`: consolidation logic that consumes stored experiences.
- `db_helper.py`: database helper utilities.
- `cache.py`: async LRU cache utilities.

## Primary flows

- `store_experience(domain=..., payload=...)` for append-only experience records.
- `save_workflow_state(...)` / `get_workflow_state(...)` for DAG state persistence.

## Operational notes

- SQLite DB location: `.adami_data/l2_memory.db`
- `skill_metadata` is append-only; consumers should prefer “latest record per skill_name”.

