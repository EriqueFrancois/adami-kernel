#!/usr/bin/env bash
#
# Purpose: Headlessly generate a Report Studio-style daily Markdown note under a
#   SecondBrain tree (same API path as interactive `/report run daily`, without
#   starting the kernel EventBus). For full interactive behavior, use the shell.
#
# Prerequisites: Poetry, `poetry install` at repo root (package `adami_kernel` importable).
#
# Exit codes:
#   0 — Wrote `Inbox/report-*.md` (path printed on stdout).
#   1 — Python/runtime error (see stderr).
#   2 — Could not resolve repository root or `cd` to it.
#   3 — `poetry` not found in PATH (documented skip: run the kernel interactively).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)" || exit 2
cd "$ROOT" || exit 2

if ! command -v poetry >/dev/null 2>&1; then
  echo "Run interactive: install Poetry, run \`poetry run adami\`, then send \`/report run daily\` (see \`report.help.body\` for /report list|show|set)." >&2
  exit 3
fi

exec poetry run python scripts/examples/report_studio_to_secondbrain_write.py "$@"
