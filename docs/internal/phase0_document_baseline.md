# Phase 0 — Document baseline lock (Hermes-alignment prep)

**Purpose**: Freeze fingerprints of key docs before Phase 1–3 edits so PRs can cite a reproducible pre-change baseline. No user-facing feature.

**Branch**: `feat/doc-wiki-hermes-phase0` (created at Phase 0 execution).

**Git commit**: Repository had **no commits yet** at lock time; there is no `HEAD` hash. After the first commit on this branch, update this file with `git rev-parse HEAD` or replace this section in the PR description.

**Lock time (UTC)**: 2026-04-12 (record exact time in PR if needed).

## SHA256 of tracked content (pre–Phase 1 edits)

Compute locally: `shasum -a 256 <file>`.

- `README.md` — `d0e8a9f097e94791f98b23782c05e6ff1c0cf19af12131178dce0e3b806a3eb8`
- `docs/standard/en/ARCHITECTURE.md` — `d3cc79e8305b4ad9dbfe2837bdd41d698bd934287030992f91f43ebddc2f64f7`
- `docs/standard/zh/ARCHITECTURE.md` — `9fe2c65d743c5c8978e799de2865e5a3bd7e7fa372a28c6372363ff2ac2c0049`

If any hash differs after your local edits, the baseline drifted — refresh this file in the same PR as the doc changes.

## Key detection (Report Studio smoke)

**Command** (use project venv; **do not** set `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` for this pair, or async tests lose `pytest-asyncio` and fail):

```bash
poetry install
poetry run python -m pytest tests/test_report_studio_template_locale.py tests/test_report_port_format.py -q
```

**Result at lock**: 5 passed.

## Notes

- i18n parity tests elsewhere may still use `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`; that is intentional for plugin isolation, not for this Report Studio subset.
