## vNext roadmap (quarter) — AdamI kernel upgrades

This roadmap is optimized for **practical agent usefulness** and compounding progress (measurable improvements),
while staying aligned with 2026 agent ecosystem trends (**MCP**, agent interoperability, eval/observability discipline).

See audit: `docs/audit/v1_0_alpha_audit.md`.

---

## Guiding principles (vNext)

- **Evals before capability sprawl**: add new capabilities only when we can *measure* and *regress-test* them.
- **One task lifecycle contract** across CLI / Telegram / Discord.
- **Interop boundary is a feature**: tools and specialist agents should plug in without bespoke adapters.
- **AGI maturity rubric**: vNext milestones should advance measurable autonomy, learning loops, safety, and interop (see `docs/vnext/agi_asi_alignment.md`).

---

## Milestone A (Weeks 1–4): Reliability + task lifecycle UX contract

### Deliverables

1. **Task lifecycle contract**
   - Standard user-visible states: `queued` → `started` → `running` → `done|failed|timeout|cancelled`.
   - Every state includes `trace_id` (and `workflow_id` when applicable).
   - Channel-specific rules:
     - Telegram: avoid filler chat spam; prefer callback toasts and a single pinned progress message.
     - Discord: use ephemeral acknowledgements for queueing where possible.
     - CLI: keep prompt clean; show one-line status and explicit “queue position”.

2. **Timeout budget model**
   - Keep hard timeouts (`ADAMI_CLI_TASK_HARD_TIMEOUT_SEC`, `ADAMI_TASK_HARD_TIMEOUT_SEC`) but add:
     - per-tool-call timeouts (web, MCP, LLM) with explicit “budget exceeded” classification.
     - cancellation propagation guidelines (best-effort, non-fatal cleanup).

3. **Queue health tooling**
   - New commands (CLI + text commands) to:
     - `/queue status` (pending count, in-progress age, oldest pending age)
     - `/queue cancel` (cancel current task)
     - `/queue discard` (clear pending + in-progress)
     - `/queue export-trace` (dump last trace ids or paths)

4. **Config knobs (exposed via settings wizard)**
   - `ADAMI_CLI_TASK_HARD_TIMEOUT_SEC`, `ADAMI_TASK_HARD_TIMEOUT_SEC`
   - `ADAMI_TASK_QUEUE_TTL_SEC`, `ADAMI_TASK_QUEUE_IN_PROGRESS_TTL_SEC`
   - `ADAMI_EVENT_CONSUMER_MAX_CONCURRENT`

### Acceptance criteria

- A stuck tool call cannot block the queue longer than configured hard timeout.
- Users can always tell whether a request is queued vs running vs done.
- No “filler reply spam” regressions in Telegram (unit + scenario tests).

---

## Milestone B (Weeks 5–8): Eval & replay backbone (compounding engine)

### Deliverables

1. **Golden traces**
   - A small curated dataset of NDJSON traces (representative tasks):
     - report generation (`/report run daily`)
     - intake (short knowledge note)
     - workflow execution path (planner → engine)
     - tool failure / timeout path

2. **Replay runner (developer-facing)**
   - Extend existing replay skeleton (`src/adami_kernel/integration/sim/replay.py`) into:
     - deterministic replay with mock injection hooks for LLM/web/MCP
     - assertion packs (topic/order/payload shape)
     - a scored summary report (pass/fail + reasons)

3. **Agent quality scorecards**
   - Track: correctness, safety, latency, cost, “noise” (unnecessary replies).
   - CI gates for “no regression” on golden traces.

### CI gates (suggested)

- **Unit + acceptance**: keep existing pytest suite.
- **Replay gate**: run a small golden trace pack with mocks and emit an artifact report.

### Acceptance criteria

- Every PR can run a replay suite locally and in CI with stable outputs.
- We can compare v1.0-alpha vs vNext behaviors using the same trace pack.

---

## Milestone C (Weeks 9–12): Interop expansion (MCP + agent-to-agent boundary)

### Deliverables

1. **MCP as first-class tool surface**
   - Documented configuration, allow/deny policy, timeout behavior.
   - Observability mapping: each MCP tool call produces trace spans and structured audit metadata.
   - Safe defaults (deny-by-default unless allowlisted).

2. **A2A-style inter-agent boundary**
   - A minimal message schema for:
     - delegation, handoff, result return
     - approval requests (HITL-like)
   - Transport abstraction (initially in-process; later could be HTTP/WebSocket/queue).

### Ecosystem alignment (2026)

- Treat interop as layered, not competing: **MCP (tools)** + **A2A-style (agents)**.
- Build **observability into the boundary** so buyers can audit “who called what, when, and why”.

### Config knobs (interop)

- MCP: `ADAMI_MCP_ENABLED`, `ADAMI_MCP_SERVERS_JSON`, `ADAMI_MCP_ALLOW_TOOLS`, `ADAMI_MCP_DENY_TOOLS`, `ADAMI_MCP_TIMEOUT_SEC`

### Acceptance criteria

- A third-party MCP server can be added with a documented procedure and produces traceable, auditable tool calls.
- A specialist agent can be integrated without changing the core `DecisionProcessor` logic (only via boundary).

---

## Out of scope (for this quarter)

- Full enterprise identity (SSO/SCIM) and multi-tenant control plane.
- Billing/usage metering beyond basic observability counters.
- “AGI claims” — focus is compounding practical reliability and measurable improvements.

