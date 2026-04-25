## Purpose

`skill_manager/` owns the **skill lifecycle**:

- naming and routing (`SkillRouter`)
- code generation (factory/backends)
- building, validation, inspection, and loading
- metadata + versioning + cleaning
- vector store indexing / retrieval

## Key files

- `skill_router.py`: detects skill creation vs invocation intents; normalizes/infer skill names.
- `skill_factory.py`: multi-tier code generation (template/Anthropic/GitHub/LLM fallbacks).
- `skill_builder.py`: writes skill code to disk and coordinates validation hooks.
- `skill_validator.py`: static validation of skill code.
- `skill_inspector.py`: runtime inspection / quality gate (optionally sandboxed).
- `skill_loader.py`, `skill_file_loader.py`: loads skills into `EvolutionEngine` runtime.
- `skill_metadata.py`: metadata models (status/metrics/versions).
- `skill_version_manager.py`: cached metadata store + periodic flushing.
- `skill_cleaner.py`: garbage collection of unused/polluted skills.
- `vector_store.py`: vector index integration.

## Primary flows

- **Create skill**
  - Orchestrator/agents produce code → `skill_builder.build(...)` → validate → load → update metadata → index

- **Cleanup**
  - `skill_cleaner.clean()` → delete files + remove from vector store + mark metadata as `deleted`

