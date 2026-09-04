# Changelog

This project follows a pragmatic changelog style: releases highlight **operator-visible changes**,
defaults/safety gates, and migration notes. For deep technical details, refer to the docs under
`docs/`.

## v1.0.0-alpha

Initial alpha release for early adopters.

### Highlights

- **Multi-channel kernel**: unified workflow execution path across CLI / Web / Telegram / Discord.
- **Workflow engine**: DAG-based execution with pause/resume/audit via persisted state.
- **Intent adaptive pipeline**: optional tiered intent routing (rules → optional LLM → templates → Planner fallback).
- **Observability**: OpenTelemetry traces + metrics, with explicit sampling and export redaction policy.
- **Safety controls**: sensitive redaction middleware, skill AST auditing, optional sandboxed execution.

### Notes

- This is an **alpha** release: APIs and defaults may change.

## v0.2.2 — 2026-09-04

Package version in `pyproject.toml` is now **0.2.2**.

### Fixed

- **CI `lint-and-gates`**: `ruff check src/ tests/` is green. Import order (`I001`) from the 0.2.1
  planner-scratchpad import is sorted; historical `F821` (`boot_t`, `_out`, `effective_locale`,
  `META_CORTEX_PERSONA`) and leftover unused/B010/zip-strict issues in the same gate are cleared.

## v0.2.1 — 2026-09-03

Package version in `pyproject.toml` is now **0.2.1**.

### Fixed

- **Morning brief (Telegram)**: Circadian 09:00 no longer publishes the free-form planner “每日晨会”
  prompt. That job raced Report Studio’s `/report run daily`, retrieved April `Inbox/report-*` notes,
  and leaked nested JSON (`original_task`, `second_brain_snippets`, `previous_result`) as the first
  chat message.
- **SecondBrain retrieve**: skip Report Studio notes; prefer filename dates so old briefs are not
  treated as today’s news.
- **Planner / DecisionProcessor**: do not send internal scratchpad JSON to the user; `/report run`
  skips the SecondBrain path line on Telegram/Discord and the extra “done” footer.

## v0.2.0 — 2026-09-02

Package version in `pyproject.toml` is now **0.2.0**.

### Added

- **Evals & replay (Milestone B)**: curated golden trace suites under `docs/evals/traces/`, deterministic
  replay runner (`adami-replay-run`), suite evaluator (`adami-replay-eval`), and comparison reports
  (`adami-replay-compare`) with configurable regression thresholds (`--max-score-drop`, `--max-dim-drop`).
- **Strong replay gates**: `adami-replay-run --verify-isomorphic` (strict isomorphism check) and
  `--inject-all-records` (full record injection) with explicit allowlists under
  `docs/evals/traces/isomorphic_gate.json` and `docs/evals/traces/inject_all_gate.json`.
- **Fault injection (Phase 3)**: `adami-replay-run --faults <faults.json>` to simulate drops/raises/payload
  mutations and emit faulted traces + eval reports (CI smoke test expects failure).
- **Operability hard gate**: `min_operability` threshold in per-trace `scorecard.json` and suite reports.
- **Diagnostics modules**: in-process `CuriosityQueue`, `EndocrineSystem` (`calm|normal|stressed|overloaded`
  from limiter + queue depth), and `WoofishPredictor` (short-horizon wait/timeout risk). Wired through
  `ComponentInitializer` / `LifecycleManager`; `SystemDiagnostics.perform_startup_check` runs at boot
  (non-fatal) via `ComponentsKernelView`.
- **json-repair**: declared Poetry dependency; parser still falls back if the import fails.
- **Queue TTL sweeper**: `ADAMI_TASK_QUEUE_SWEEP_SEC` (default 60s) persists expired pending/in-progress rows.

### Changed

- **Pending queue TTL** default is **3600s** (`ADAMI_TASK_QUEUE_TTL_SEC`); recovered in-progress items keep
  their original `started_at` so restarts cannot reset age.
- **Messenger boot** no longer pushes “system ready” or pending-queue buttons unless
  `ADAMI_MESSENGER_NOTIFY_BOOT` / `ADAMI_TASK_QUEUE_NOTIFY_ON_BOOT` are enabled.
- **Telegram**: `ADAMI_TELEGRAM_DROP_PENDING_UPDATES` defaults to true so downtime getUpdates are not
  treated as fresh user tasks.
- **transformers**: optional import only when torch is present so `multi_modal` loads without HuggingFace.
- **DecisionProcessor**: offline sim scenarios (`/toolchoice`, queue flows, planner multistep, intake)
  live in `integration/sim/dp_offline_scenarios.py`.

### Fixed

- **Task queue**: prevent a stuck task from blocking all subsequent queued tasks by adding a
  non-CLI hard timeout (`ADAMI_TASK_HARD_TIMEOUT_SEC`, default **900s**) and expiring stale in-progress
  rows on load/save (`ADAMI_TASK_QUEUE_IN_PROGRESS_TTL_SEC`, default **900s**).
  CLI hard timeout (`ADAMI_CLI_TASK_HARD_TIMEOUT_SEC`) is also **900s** by default and can be changed
  via the CLI System settings wizard.
- **Report (Telegram)**: removed the extra “queued/processing” chat message for the one-click
  immediate report buttons (keeps the callback toast, avoids noisy filler replies).
- **EventBus DLQ spam loop**: RBAC-denied events are no longer enqueued into DLQ (prevents replay spam),
  and a new operator kill-switch `ADAMI_DLQ_CLEAR_ON_BOOT` can clear DLQ once on boot after upgrades.
- **ComponentInitializer**: restore `EvolutionEngine` import required for boot/replay.

## Unreleased

_Nothing yet._


