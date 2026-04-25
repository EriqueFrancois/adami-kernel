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

