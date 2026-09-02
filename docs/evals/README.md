## Evals & replay (developer guide)

AdamI has a strong unit/integration test suite, but practical agent progress requires **behavior regression tests**:
**golden traces + deterministic replay + scoring + CI gates**.

This document describes what exists **today** in vNext (Milestone B deliverables) and how to use it.

### What exists today (vNext / Milestone B)

- **Golden trace suite pack** under `docs/evals/traces/` (see `docs/evals/traces/README.md`)
- **Replay runner** (exports replayed trace; supports strong verification/gates):
  - `poetry run adami-replay-run <trace.ndjson> --out-trace <replayed.ndjson>`
  - `--verify-isomorphic`: strict record-by-record isomorphism check (with normalization)
  - `--inject-all-records`: inject all trace records (stronger than prompt-only)
  - `--full-kernel`: prompt-driven run (inject `user.prompt`, let DP run naturally)
  - `--faults <faults.json>`: Phase 3 fault injection; can also emit eval reports
- **Replay eval** (suite-level JSON + Markdown artifacts):
  - `poetry run adami-replay-eval --suite-dir docs/evals/traces --out-json out.json --out-md out.md`
- **Compare reports** (baseline vs head suite diff + thresholds):
  - `poetry run adami-replay-compare --baseline-json base.json --head-json head.json --out-json cmp.json --out-md cmp.md`
  - Thresholds: `--max-score-drop`, `--max-dim-drop`
  - Ref mode (cross-generation compatible): `--baseline-ref <ref> --head-ref <ref> --suite-dir ... --out-dir ...`

### CI gates (summary)

CI is wired to run (a) suite eval gates, (b) strong isomorphic gates, and (c) inject-all gates on an allowlist.

- Allowlist configs:
  - `docs/evals/traces/isomorphic_gate.json`
  - `docs/evals/traces/inject_all_gate.json`
- Fault injection smoke (expected failure) is also wired in CI to prove the pipeline end-to-end.

### Practical scorecards (what we gate)

Each trace has a `scorecard.json` with explicit thresholds. Core dimensions:

- **Correctness**: task completion and required fields present
- **Safety**: forbid leaks / enforce redaction and hard rules
- **UX**: user-visible reply quality; no confusing/filler responses
- **Noise**: avoid unnecessary “ok/anything else?” spam (hard + soft gates)
- **Operability**: tool lifecycle completeness and actionable error/timeout handling
- **Latency/Cost**: best-effort performance proxies for stable regressions

