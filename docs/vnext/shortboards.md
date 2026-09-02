## vNext shortboards (prioritized) — what blocks “useful agent”

This is the prioritized “missing pieces” list for AdamI as a **practical agent kernel**.
Each item includes concrete acceptance criteria so progress is measurable.

See: `docs/audit/v1_0_alpha_audit.md` and the quarter plan in `docs/vnext/roadmap.md`.

---

## 1) Eval & replay first-class (quality regression harness)

**Problem**: without behavior evals, adding features increases drift risk and slows iteration.

**Acceptance criteria**

- A curated set of “golden traces” exists and is runnable locally + in CI.
- Replay produces a deterministic report: pass/fail assertions + summary metrics (latency/cost/noise).
- PRs can prove “no regression” on core scenarios (report/intake/workflow/tool failure).

Recommended home: `docs/evals/README.md` and `docs/evals/traces/…`.

---

## 2) Unified task lifecycle UX contract (no noise, no confusion)

**Problem**: multi-channel agents fail in practice when users can’t tell queued vs running vs done, or get spammy filler.

**Acceptance criteria**

- All channels use the same lifecycle states: `queued|started|running|done|failed|timeout|cancelled`.
- Every task shows a `trace_id` (and `workflow_id` when present) in at least one operator-visible message.
- Telegram/Discord default path produces at most:
  - 1 queue ack (toast/ephemeral preferred), 1 progress message, then the final result.

---

## 3) Tool boundary productization (MCP)

**Problem**: MCP plumbing exists, but “sellable” requires docs + policy + observability + safe defaults.

**Acceptance criteria**

- A documented MCP setup that works end-to-end with allow/deny policy.
- Each MCP tool call is traced (`tool.mcp.call`) and audit metadata is recorded (redacted args, latency).
- Operators can list installed MCP tools and see whether allowlist/denylist is in effect.

---

## 4) Agent-to-agent interoperability (A2A-style boundary)

**Problem**: internal multi-agent exists, but external specialist agents can’t plug in cleanly.

**Acceptance criteria**

- A minimal message schema for delegation/handoff/result is implemented and documented.
- A transport abstraction exists (start with in-process adapter) so tests can run deterministically.
- Every A2A exchange is traced and respects redaction.

---

## 5) Memory quality (retrieval + citations + write governance)

**Problem**: keyword bounded retrieval is intentionally safe, but limits “practical agent” performance.

**Acceptance criteria**

- Optional retrieval modes:
  - current keyword bounded (default)
  - deeper search (explicitly opt-in; scoped; performance bounded)
- Every answer that uses memory includes lightweight citations (file/path or note id).
- Memory writes are policy-governed (dedupe keys, provenance tags, avoid secrets).

---

## 6) Operational hardening (policy profiles + diagnostics)

**Problem**: production adoption needs clear “what is enforced” and operator evidence.

**Acceptance criteria**

- A `self-check` report summarizes: sandbox availability, redaction on/off, MCP allowlist, OTel exporter, queue settings.
- A “safe mode” exists to disable external tools and run local-only for incident response.

