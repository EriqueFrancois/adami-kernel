# AdamI — Whitepaper (value & positioning)

**Audience**: investors, executives, M&A — **not** a substitute for legal DD.

This document explains **why the architecture matters commercially**. It avoids implementation trivia; verify engineering claims in `ARCHITECTURE.md` / `SECURITY.md`.

---

## 1. Market pain (agent systems today)

| Pain | Symptom for the buyer | AdamI direction |
|------|----------------------|-----------------|
| **Volatile memory** | Every restart loses context; “the agent forgot” | SQLite-backed `LayeredMemory`, SecondBrain notes, append-only experience sinks |
| **Runaway execution** | Unbounded async tasks, provider storms | `system.events` consumer with **semaphore cap**, DLQ discipline |
| **Un-auditable chains** | Cannot reconstruct who approved what | `WorkflowEngine` persists DAG state; HITL topics for human gates |
| **Prompt injection & secret bleed** | Keys in logs, screenshots, tickets | Bus middleware **redaction**, vault-style signing keys, AST washers on ingested code |
| **Integration tax** | Each channel reimplements routing | Unified `AdamiEvent` + `EventBus` + platform nerves |

---

## 2. Differentiation (moat framing)

1. **Kernel, not demo**: explicit lifecycle, typed events, orchestration — suitable for regulated workflows when wrapped with your org policies.
2. **Evolutionary skill loop**: GitHub / LLM-sourced skills pass **static audit** and **washing** before joining the runtime (see `SECURITY.md`).
3. **Operational artifacts**: Report Studio (`/report run …`) turns scheduled research-style outputs into durable notes — a concrete **B2B workflow** SKU (enablement, compliance packs, analyst desks).

---

## 3. Commercial scenarios (illustrative)

> **Important**: The open repository does **not** ship broker credentials or live trading keys. Any **PnL or latency figures** must come from **your** controlled evaluation — do not treat marketing placeholders as audited performance.

- **Research & briefing desks**: daily/weekly/monthly reports with configurable sections, persisted to SecondBrain paths.
- **Internal copilots with audit**: DAG state + HITL for approvals in procurement / legal review (policy layer is yours).
- **Managed agent hosting**: multi-channel nerves (Telegram/Discord/CLI) with one decision core — reduces per-surface engineering cost.

---

## 4. Revenue & packaging (suggested lenses)

- **OSS core + commercial services**: onboarding, hosted bus, enterprise SSO, VPC-bound models.
- **Acqui-hire value**: team demonstrates **systems** skills (async kernel, sandboxing, i18n gates) beyond prompt engineering.

---

## 5. Risks (honest)

- **Dependency surface**: LLM vendors, Docker availability for sandboxes, optional bridges (e.g. DeerFlow) add ops burden.
- **Security is process**: open code helps DD, but **your** deployment must still run penetration tests and secret rotation.

---

## 6. Call to action

- Technical buyers: clone, run `poetry run adami`, read `ARCHITECTURE.md`.
- Commercial buyers: pair this document with your internal ROI model; request a controlled pilot with trace export enabled.
