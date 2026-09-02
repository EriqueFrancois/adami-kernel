## AGI/ASI alignment (engineering standards) — AdamI north star

This document translates “mature AGI / ASI” into **engineering standards** that can guide long-term development
without relying on hype claims. It complements the quarter roadmap (vNext) by defining what “mature” means
in measurable terms.

### Definitions (pragmatic)

- **AGI (mature, practical)**: can reliably solve a wide distribution of novel tasks with minimal hand-holding,
  learns from experience, and operates safely under constraints.
- **ASI**: exceeds human capability across most cognitive tasks and improves itself rapidly.

In an open-source kernel context, “getting closer” is about **capabilities + reliability + measurement + safety**.

---

## 1) Maturity rubric (what a mature AGI system must have)

> For the detailed, testable 5-level acceptance rubric, see: `docs/vnext/agi_acceptance_levels.md`.\n

### A) Autonomy with bounded risk

- **Goal decomposition**: turns user intent into a plan/workflow with checkable intermediate states.
- **Long-horizon execution**: survives partial failures and resumes from persisted checkpoints.
- **Budgeting**: time/cost/tool budgets are explicit and enforced.
- **Interruption & control**: humans can pause/cancel/override at any point.

### B) Learning that compounds (not just logs)

- **Evaluation harness**: behavior regression tests (golden traces) + scoring.
- **Experience → policy loop**: lessons are distilled into rules/policies/templates that reduce future failures.
- **A/B comparability**: every change can be compared “before vs after” using the same replay suite.

### C) World model & memory governance

- **Memory write discipline**: provenance, dedupe keys, secrets policy, and “why it was stored”.
- **Retrieval with citations**: answers that use memory include references (paths/ids) to support audit.
- **Contamination controls**: prompt-injection resistant ingestion; “untrusted content” is tracked as such.

### D) Tool & agent interoperability

- **Tool boundary**: standardized tool protocol with policy and observability (MCP-style).
- **Agent boundary**: standardized agent-to-agent delegation lifecycle (A2A-style), transport-agnostic.

### E) Safety as a system property

- **Redaction** (logs/traces/events) + **sandboxing** (execution isolation) are defaults, not optional afterthoughts.
- **High-risk actions require explicit consent** (HITL) with durable audit records.
- **Attack surface is observable**: tool calls are traced and attributable.

---

## 2) Where AdamI is strong today

AdamI already contains several “AGI maturity primitives”:

- Kernelized event-driven architecture with bounded concurrency and persistent workflows.
- Persistent per-chat task queue and hard-timeouts for stuck tasks.
- Security building blocks: redaction middleware, skill auditing/washing, optional sandbox.
- Observability foundation: OTel sampling + export-time redaction.
- Replay skeleton (validation + inject hooks) that can be upgraded into a full eval harness.

---

## 3) Biggest AGI/ASI blockers (shortboards)

In order of compounding value:

1. **First-class evals** (golden traces + replay + scoring) — without this, “self-evolving” can’t be trusted.
2. **Unified lifecycle contract** across channels and across agent/tool boundaries.
3. **Budgeting + cancellation** down the stack (planner → tools → workflows).
4. **Interop boundary** (MCP tools + A2A agents) with policy + observability.
5. **Memory governance + citations** (improve capability without losing auditability).

---

## 4) How this maps to vNext (one quarter)

How to judge quarter deliverables against the north star:\n
- This document defines the **direction** (autonomy, compounding learning, memory governance, interop, safety).\n
- The 5-level rubric (`agi_acceptance_levels`) defines the **gates** (measurable criteria + runnable suites).\n
- The vNext quarter roadmap defines **near-term deliverables** that must map to prerequisite gates of higher levels.\n

The quarter roadmap should be judged against this rubric:

- Milestone A: enforces **bounded autonomy** (timeouts, lifecycle UX, control).
- Milestone B: builds **compounding learning** (evals + replay + scorecards).
- Milestone C: defines the **interop boundaries** needed for ecosystem-scale capability growth.

