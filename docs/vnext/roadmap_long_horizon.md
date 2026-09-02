## Long-horizon roadmap (AGI → ASI direction)

This is the “north star” roadmap beyond the next quarter. It is grounded in
`docs/vnext/agi_asi_alignment.md` and should be treated as **direction**, not a near-term promise.

> For the testable 5-level acceptance rubric, see: `docs/vnext/agi_acceptance_levels.md`.\n

---

## Current position (2026-04) and 3–5 year target

- **Current**: broadly **Level 1 (Emerging / Chatbots)**, with several maturity primitives already present (event bus, workflow skeleton, persistent queues, replay skeleton, observability).\n
- **3–5 year target (pragmatic)**:\n
  - reach a stable **Level 2** (measurable reasoning, structured-output reliability, auditable verifier loops);\n
  - build the engineering closure needed for **Level 3** (long-horizon autonomy, recovery, budgeting + cancellation propagation, interop boundaries).\n

The plan below is organized by capability tracks.\n

## Phase 1: Measurable autonomy (quarters 1–2)

- **Evals as a release gate**: golden traces + replay + scoring become mandatory for core paths.
- **Budgeting everywhere**: time/cost/tool budgets per task and per tool call, with clear failure modes.
- **Unified lifecycle contract**: a single task/agent lifecycle model shared by CLI/TG/DC and external boundaries.
- **Operator controls**: pause/cancel/resume + evidence artifacts (trace ids, workflow state snapshots).

## Phase 2: Safe capability expansion (quarters 2–4)

- **Tool ecosystem scaling**:
  - MCP servers become a curated catalog with allowlist policies and trust tiers.
  - Tool annotations drive governance (readOnly/destructive/openWorld → confirmation policies).
- **Memory upgrades with governance**:
  - richer retrieval modes (opt-in) + citations by default
  - ingestion sanitation + untrusted-content tracking
- **Agent specialization**:
  - external specialist agents via A2A-style boundary
  - internal role agents become pluggable modules with eval suites

## Phase 3: Self-improvement loops (year+)

- **Experience distillation**:
  - convert failure clusters into policies, templates, and tests automatically
  - “learning outputs” are versioned and audited
- **Automated safety regression**:
  - adversarial test packs for prompt injection, secret leakage, and tool misuse
- **Meta-optimization**:
  - the system proposes changes, but promotion requires passing eval gates and explicit approvals

---

## 3–5 year development plan (by capability tracks)

> Every track must produce runnable acceptance artifacts (golden traces / replay / scorecards / fault suite / audit evidence).\n

### Track A: Evaluation & regression (learning that compounds)

- **0–12 months (L1→L2 prerequisites)**\n
  - Expand `docs/evals/traces/`: planner core paths, tool failures/timeouts, cancellation propagation, queue recovery, memory citations.\n
  - Make scorecards hard gates: correctness / operability / UX-noise / safety.\n
- **12–24 months (reach L2)**\n
  - Add verifier traces: structured verification outputs with separate scoring.\n
- **24–60 months (L3 prerequisites)**\n
  - Industrialize fault suite: network jitter, 429, API schema drift, MCP server failures; enforce recovery-rate gates.\n

### Track B: Lifecycle contract & bounded autonomy

- **0–12 months**\n
  - Unify lifecycle semantics across ports: queued/started/running/done|timeout|cancelled.\n
  - Budgeting + cancellation propagation down the stack (planner→workflow→tools).\n
- **12–24 months (L2→L3 prerequisites)**\n
  - Checkpoint/resume: long tasks can pause/continue across process restarts.\n
- **24–60 months (reach L3)**\n
  - 48h+ autonomy (sim) passes under fault injection with rollback/retry strategies.\n

### Track C: Tool & agent interop boundaries (MCP + A2A)

- **0–12 months**\n
  - MCP as first-class boundary: allow/deny, timeouts, audit metadata, span mapping.\n
  - A2A minimal message schema: delegation/handoff/approval/result, transport-agnostic.\n
- **12–24 months (L3 prerequisites)**\n
  - Role agents (planner/executor/reviewer/debugger) become pluggable and eval-bound.\n
- **24–60 months (reach L3)**\n
  - External specialist agents integrate without core DP changes; expansion remains auditable.\n

### Track D: Memory governance & citations

- **0–12 months**\n
  - Write discipline: provenance, dedupe keys, risk tiers, “why stored”; ingestion injection hardening.\n
  - Retrieval with citations by default.\n
- **12–24 months (reach L2)**\n
  - Trusted/untrusted tiers + contamination controls; measurable regressions for memory-based behavior.\n
- **24–60 months (L3 prerequisites)**\n
  - Persist “world state” checkpoints as workflow-resumable artifacts.\n

### Track E: Safety & operations

- **0–12 months**\n
  - HITL for high-risk actions + durable audits; redaction defaults.\n
  - UX-noise gates (busy/queued/toast consistency across ports).\n
- **12–24 months (L3 prerequisites)**\n
  - Sandbox by default: least-privilege filesystem/network/command execution policies.\n
- **24–60 months (reach L3)**\n
  - Chaos-style regression: node crashes, data corruption, compute loss → preserve core continuity.\n

## What “ASI” would imply (guardrails)

Even if capability accelerates, the kernel must preserve:

- **human override** and bounded authority
- **auditability** (who/what/when/why)
- **measurable safety** (redaction/sandboxing/policy enforcement)

