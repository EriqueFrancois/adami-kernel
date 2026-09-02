## AGI north-star acceptance rubric (Level 1–5) — AdamI

This document defines **testable, engineering acceptance gates** for AdamI’s long-term AGI maturity.\n
Positioning:\n
- `docs/vnext/agi_asi_alignment.md` captures **principles and direction**.\n
- This document captures **acceptance and gates**: what “done” means and how to prove it.\n

> Rule: every acceptance criterion must map to at least one runnable artifact: pytest, replay suite (`adami-replay-eval`), golden traces, or fault-injection reports.\n

---

## Shared requirements (all levels)

### Lifecycle contract (CLI / Telegram / Discord)

- States: `queued → started → running → done|failed|timeout|cancelled`\n
- Cancellation: must **propagate best-effort**, **release session lock**, and allow queued tasks to continue.\n
- Timeouts: hard-timeout must release the session and emit a user-visible explanation.\n

### Minimum observability

- **trace_id**: at least one user-visible message per task includes a traceable identifier.\n
- **source isolation**: internal telemetry events must not re-enter the user intent path.\n
- **replay comparability**: the same traces can compare baseline/head behavior.\n

---

## Level 1 — Emerging / Chatbots

### Definition

Natural conversation at roughly “ordinary human” level; weak state; request-response dominates and relies on external context.

### Engineering essence (architecture signature)

- A mostly linear pipeline: **Intent Router → Prompt Builder → LLM**.\n
- Per-chat **session lock + persistent queue** ensures the system doesn’t stall indefinitely.\n

### Acceptance criteria (measurable)

- **Context retention**: within a fixed prompting policy (e.g. 128k window strategy), factual recall ≥ 95%.\n
- **Instruction following**: JSON/Markdown parsing failure ≤ 2% under standard prompting.\n
- **Low-noise UX**: busy/queued/timeout messaging is rate-limited consistently across platforms.\n
- **No telemetry re-entry**: internal events (e.g. router/tool telemetry) do not trigger `DecisionProcessor` routing.\n

### Required instrumentation

- Event-consumer logs include: `trace_id/source_module/chat_id/task`.\n
- Lifecycle state transitions can be captured in replay traces.\n

### Standard test suites

- **Single prompt, single reply**: one-line `hello` produces **≤ 1 user-visible reply**.\n
- **Queue UX**: `/queue status|cancel|discard|export-trace` consistent across platforms; i18n parity green.\n
- **Telemetry isolation**: injecting a `system.events` record with `source_module=cortex.router` and empty `payload.task` must not route through `DecisionProcessor`.\n

### Exit gate

- 50+ golden traces stable under replay; covers Direct Answer, planner, tool failures, busy/queued/timeout/cancel.\n
- `tests/test_i18n_locale_key_parity.py` must pass.\n

---

## Level 2 — Competent / Reasoners

### Definition

Competent, single-task reasoning at meaningful expert utility; introduces self-correction and verifier loops.

### Engineering essence

System 2: **generator-verifier loops** where verification is an *engineered* step that is replay-evaluable (not “mystical CoT”).

### Acceptance criteria

- **Multi-step reasoning (no tools)**: consistent correct outcomes with self-correction.\n
- **Structured output reliability**: complex schemas pass-at-once improves materially.\n
- **Reasoning is measurable**: scorecards include correctness / hallucination risk / completeness.\n

### Required instrumentation

- Verifier outputs are structured and recorded in traces.\n
- Replay can score verifier and solver phases separately.\n

### Standard test suites

- **Static deadlock reasoning**: identify deadlock path and refactor plan without execution.\n
- **SWE-bench Lite (or kernel task set)**: express thresholds as scorecard gates (Pass@1 + quality constraints).\n

---

## Level 3 — Expert / Agents (architectural watershed)

### Definition

Long-horizon, multi-day execution; “actor” not just “thinker”; high robustness and recovery.

### Engineering essence

- Multi-agent orchestration + workflow DAG + checkpoint/resume.\n
- Explicit budgets and cancellation propagation.\n

### Acceptance criteria

- **48h autonomy (sim)**: survives 48h+ under replay + fault injection.\n
- **Error recovery ≥ 85%** for tool/API failures (as defined by the fault suite report).\n
- **Human control**: pause/cancel/override always works; resumes from checkpoints.\n

### Standard test suite

- **CVE patch PR** under constrained permissions: fetch repo, patch, run tests, and produce a reviewable PR artifact.\n

---

## Level 4 — Virtuoso / Innovators

### Definition

Invents and validates new tools/skills; compounding improvement is measurable and gated.

### Engineering essence

Self-evolving skill loop: detect gaps → synthesize/modify skills → test → register → reuse.

### Standard test suite

- **Invent → test → register → reuse** traces; reuse must depend on the newly registered skill.\n

---

## Level 5 — Superhuman / Organizations

### Definition

System-of-systems: organization-level autonomy, IaC control, chaos survivability, and strong governance.

### Directional gates

- Strategic intent → operational plans with auditable artifacts.\n
- Chaos survival under node outages / data corruption / compute loss.\n

