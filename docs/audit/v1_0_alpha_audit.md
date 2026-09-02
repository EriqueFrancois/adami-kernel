## AdamI v1.0.0-alpha — audit (practical agent kernel)

**Scope**: evaluate the shipped `v1.0.0-alpha` as a *practical*, production-leaning agent kernel.
This is not a penetration test. Engineering claims are grounded in the repository sources.

### Sources reviewed (primary)

- Product promise: `README.md`, `CHANGELOG.md`
- Technical boundary: `docs/standard/zh/ARCHITECTURE.md`, `docs/standard/en/WHITEPAPER.md`
- Key modules (selected):
  - `src/adami_kernel/core/lifecycle_manager.py` (bounded concurrency + orchestration glue)
  - `src/adami_kernel/cortex/decision_processor.py` (routing + session locks + queue drain)
  - `src/adami_kernel/core/task_queue.py` (persistent per-chat FIFO + TTL/caps)
  - `src/adami_kernel/mcp/manager.py` (MCP server/tool registration)
  - `src/adami_kernel/integration/sim/replay.py` + `replay_cli.py` (trace validation/replay skeleton)
  - `src/adami_kernel/observability/*` (OTel policy + activity clock + messenger metrics)

---

## 1) Capability map (rubric → current state)

### Reliability (bounded concurrency, lifecycle, recovery)

- **Bounded concurrency on `system.events`**: **present**
  - `LifecycleManager` uses `asyncio.Semaphore` to cap concurrent processing (`ADAMI_EVENT_CONSUMER_MAX_CONCURRENT`).
- **Per-chat session lock**: **present**
  - `DecisionProcessor` uses `session_locks[chat_id]` to serialize per-chat work and queues new tasks if busy.
- **Per-chat FIFO queue with persistence**: **present**
  - `TaskQueueStore` persists to JSON; supports pending TTL/caps and optional Fernet-at-rest.
- **Hard-timeout to prevent indefinite lock holds**: **present**
  - CLI hard-timeout + non-CLI hard-timeout; timeouts release the lock and allow queue draining.
- **In-progress recovery after restart**: **partial**
  - Queue tracks an `in_progress` row; recovery exists (`recover_in_progress_to_front`) plus “stale in-progress TTL”.
  - Gap: “what counts as safe resume” is user/ops policy; no structured checkpoint to resume mid-tool-call.
- **Cancellation semantics**: **partial**
  - Hard-timeout cancels the task via `asyncio.wait_for`, but cancellation propagation into tool calls is inconsistent by nature.
  - Gap: consistent “budget” model per tool call and structured cancellation handling.

### Usability (onboarding, settings, predictability)

- **Fail-fast first-run initializer**: **present**
  - Refuses to boot until mandatory configuration is completed.
- **Settings wizard that persists overrides**: **present**
  - CLI config wizard writes to `.adami_data/cli_overrides.env` and supports reload.
- **Noise control (avoid filler replies)**: **improving**
  - Filler detection exists (`port.detection.filler_phrases`) but is currently “log-only”.
  - Gap: a unified “task lifecycle UX contract” across CLI/TG/DC so users always understand queued/started/running/done.

### Capability (tools, workflows, multi-agent, memory)

- **Workflow engine + persisted DAG state**: **present**
  - Strong base for long-running tasks, pause/resume/audit.
- **Multi-agent orchestration**: **present (internal)** / **interop boundary missing**
  - Multi-agent components exist, but external agent interoperability isn’t a first-class boundary yet.
- **Report Studio**: **present**
  - `/report` produces durable notes in SecondBrain and can push summaries back to IM channels.
- **Memory**:
  - **SecondBrain PARA markdown tree**: **present**
  - **Retrieval**: **partial**
    - Current retrieval is intentionally bounded (keyword match, top-level only in select PARA folders).
    - Gap: practical agent needs stronger retrieval options and citation discipline.

### Safety (redaction, sandboxing, secrets)

- **Redaction middleware**: **present** (as documented in security/architecture docs)
- **Skill auditing / washing**: **present** (static gates exist; details in security docs)
- **Sandboxing (Docker)**: **present (optional)**
  - Gap: define “policy profiles” and operator-visible checks; show exactly what is enforced in production profile.

### Operability (observability, replay, debugging)

- **Observability (OTel policy)**: **present**
  - Sampling/export redaction policies exist; messenger metrics hooks exist.
- **Replay / trace validation**: **present (skeleton)**
  - `integration/sim/replay.py` supports schema validation, basic assertions, and injection skeleton.
  - Gap: turn this into a developer-facing “golden traces + scoring” harness, not only schema validation.

### Ecosystem fit (2026 heat: MCP / A2A / evals)

- **MCP**: **present (internal plumbing)**
  - `McpManager` registers tools to the engine/toolbox and hot-refreshes when settings change.
  - Gaps: buyer/developer-facing docs, security policy (auth, allow/deny tools), observability mapping for tool calls.
- **A2A-like inter-agent boundary**: **missing**
  - Need explicit message schema and a broker/transport abstraction to talk to external agents.
- **Eval discipline**: **missing (first-class)**
  - Unit tests exist, but there is no “quality regression harness” that scores agent behavior and prevents drift.

---

## 2) Shortboards (what blocks “useful agent” the most)

In priority order for practical usability and compounding improvement:

1. **Eval + replay as a product feature** (golden traces + scoring) — enables safe iteration.
2. **Unified task lifecycle UX contract** — reduces confusion and “random feeling”.
3. **Interop boundary** — MCP as first-class tool surface; A2A-like boundary for external specialist agents.
4. **Memory quality & citations** — retrieval upgrades with clear “what came from where”.
5. **Operational hardening** — explicit policy profiles, diagnostics, and operator evidence artifacts.

