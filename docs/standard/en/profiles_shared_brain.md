# Profiles, roles, and shared SecondBrain (Hermes-style mapping)

**Audience**: operators and engineers comparing **Hermes Agent** “multi-agent + profiles + shared wiki” language to AdamI’s **workflow + MAO + SecondBrain** stack.

**SSOT code**: `src/adami_kernel/orchestrator/workflow_models.py` (`WorkflowState`), `src/adami_kernel/orchestrator/multi_agent_orchestrator.py` (`MultiAgentOrchestrator`), `src/adami_kernel/hippocampus/second_brain.py` (`SecondBrainManager`), `src/adami_kernel/config.py` (`path_second_brain_root`). If this document disagrees with those files, trust the code.

**Chinese mirror (information-equivalent)**: [`../zh/profiles_shared_brain.md`](../zh/profiles_shared_brain.md).

---

## 1. Why this mapping exists

Hermes describes **profiles** (isolated memory, sessions, skills per sub-agent) plus a **shared knowledge layer** so sub-agents do not start blind. AdamI uses different primitives—**persisted DAG state**, **`WorkflowState.context`**, and **`MultiAgentOrchestrator`** role dispatch—but the *product question* is the same: **who is isolated, what is shared, and where does long-lived knowledge live?**

---

## 2. Concept mapping (Hermes → AdamI)

1. **Hermes “profile” (per sub-agent configuration)** → **`WorkflowState.metadata`** (free-form `Dict[str, Any]`). Store a string **`profile_id`** for a stable, grep-friendly orchestration label. Kernel entry points call **`ensure_default_profile_id`** in `workflow_models.py` so new workflows get defaults (see **§3 Contract**). Other keys (for example `long_task_tracking_enabled`) already appear in real payloads—treat `metadata` as the extension point for profile-like tags.

2. **Hermes “sub-agent instance”** → **`AgentRole`**-scoped workers inside **`MultiAgentOrchestrator`** (`src/adami_kernel/orchestrator/multi_agent_orchestrator.py`), plus their **`WorkflowState.context`** entries (`engineer`, `researcher`, `_skill_name`, etc.). The orchestrator builds **`AgentMessage`** payloads per role and publishes on **`agent.communication`**.

3. **Hermes “child session / nested worker”** → **`WorkflowState.parent_workflow_id`** in `workflow_models.py`: links a child workflow instance to a parent **`workflow_id`** when you compose or fork graphs. Use it for lineage and debugging, not as a second filesystem root.

4. **Hermes “shared LLM-Wiki / knowledge base”** → **One physical SecondBrain tree** today: root from **`settings.path_second_brain_root`**, overridable with **`ADAMI_SECOND_BRAIN_ROOT`**. Shared human-readable anchors include **`Identity/TELOS.md`**, **`Identity/CONTEXT.md`**, **`Identity/PROFILE.md`**, and **`System/working-memory/OPERATING_RULES.md`**—seeded and read by **`SecondBrainManager`**. See also [knowledge_wiki_second_brain.md](knowledge_wiki_second_brain.md) for snippet retrieval scope (`retrieve_brain_snippets`).

5. **Hermes “sub-agent sees wiki context”** → In AdamI, **all roles that share the same kernel instance** read the **same** `SecondBrainManager` when the component graph wires one manager into **`PromptBuilder`** and into intake/report paths. **Per-role isolation** is primarily in **`WorkflowState.context`** and MAO message payloads, not in separate brain directories unless you deploy multiple kernels with different **`ADAMI_SECOND_BRAIN_ROOT`** values.

---

## 3. Contract (`WorkflowState.metadata`)

1. **`profile_id`** (string, optional but recommended): identifies which factory started the workflow for logs and filtering. It is **orchestration metadata only**—not read by Report Studio or SecondBrain ingest paths.

2. **`ensure_default_profile_id(state, profile_id)`** in `workflow_models.py` runs **`state.metadata.setdefault("profile_id", profile_id)`** so callers can pre-set a custom value and it will **not** be overwritten.

3. **Default writers (implemented)**:
   - **`create_initial_workflow_state`** → `profile_id="planner_initial"` (Planner quick-start states).
   - **`MultiAgentOrchestrator.start_multi_agent_workflow`** → `profile_id="multi_agent_orchestrator"`.
   - **`SkillComposer`** composed and fallback **`WorkflowState`** returns → `profile_id="skill_composer"`.

4. **Planned / manual**: tests and feature code that construct **`WorkflowState(...)`** by hand may still omit **`profile_id`** until those call sites are updated—safe because the field is optional.

---

## 4. Multi-role runtime (what logs mean)

1. **`MultiAgentOrchestrator`** keeps **`active_orchestrations: Dict[str, WorkflowState]`** keyed by workflow id and dispatches **`AgentTask`** items to registered agents (`ExecutorAgent`, Researcher, Engineer, etc.).

2. When downstream tasks need prior outputs, the orchestrator copies slices of **`state.context`** into **`AgentMessage.payload`** (for example Engineer gets **`original_task`** snippets; Executor gets **`skill_name`** / **`args`**).

3. Debug logs use i18n keys such as **`orch.magent.debug.role_ctx`** (“injected context for `{role}`: `{keys}`”)—that is the closest operational analogue to “profile-scoped context injection” in Hermes marketing language.

---

## 5. Single physical root vs future multi-root

1. **Current default**: **one** SecondBrain directory tree per running kernel configuration. That matches most single-tenant and dev setups.

2. **Strong isolation** (separate vaults per customer, separate `brain/` trees per profile) is **not** a first-class switch in this document’s scope: it would mean multiple data roots, migration, and access control—track as a later phase if product requires it.

3. Until then, **logical** isolation should be expressed with **`metadata.profile_id`**, **`chat_id`**, and **`WorkflowState.context`** boundaries, while **shared** long-form knowledge stays under the single **`path_second_brain_root`**.

---

## 6. Planner interaction (no contradiction)

1. **`Planner`** (`src/adami_kernel/orchestrator/planner.py`) may compose **`WorkflowEngine`** paths or fall back to **`MultiAgentOrchestrator`** for skill creation flows. Both paths ultimately persist **`WorkflowState`** through **`LayeredMemory`** when the engine is used.

2. This document does **not** change Planner contracts; it only names where **profile-like** and **shared-brain** concepts attach so maintainers do not invent duplicate roots.

---

## 7. Related reading

1. [knowledge_wiki_second_brain.md](knowledge_wiki_second_brain.md) — on-disk wiki narrative and `retrieve_brain_snippets` limits.
2. [ARCHITECTURE.md](ARCHITECTURE.md) — topology including Hippocampus and MAO.
3. `src/adami_kernel/hippocampus/README.md` — memory module boundaries.

---

**Document baseline**: refresh SHA256 in `docs/internal/phase0_document_baseline.md` when this file is materially edited, or record the new hash in your PR description.
