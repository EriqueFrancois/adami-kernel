## Golden trace suites

Each suite is a directory under `docs/evals/traces/` with:

- `golden_trace.ndjson`: trace records (redacted payloads, v1 schema)
- `assertions.json`: assertion pack (JSON array of `{index, assertion}` objects)
- (optional) `README.md`: scenario notes

Recommended suites:

- `minimal/`: smoke-level schema + assertions
- `report_daily/`: `/report run daily` representative flow
- `intake/`: `/intake` representative flow
- `tool_timeout/`: tool timeout/failure representative flow (safety + UX)

Additional suites (Milestone B):

- `llm_call/`: LLM call lifecycle (`TOOL_CALL_*`) coverage
- `web_search/`: web search tool lifecycle coverage
- `mcp_external/`: external/MCP tool lifecycle coverage
- `workflow_engine/`: workflow engine mainline trace (phase transitions, tool calls)
- `toolchoice/`: multi-turn LLM + tool selection (deterministic offline path)
- `planner_multistep/`: multi-step planner branch (execute_command)
- `planner_multistep_mcp/`: multi-step planner branch (MCP flaky + rollback)

Milestone A (lifecycle + queue reliability):

- `queue_status/`: queue status UX (operator-visible, no filler)
- `queue_discard/`: discard pending/in-progress queue for a chat (operator control)
- `queue_cancel_noop/`: cancel command when no task is running (safe noop UX)
- `queue_cancel_active_flow/`: cancel an active running task; verify session releases and queue continues
- `queue_timeout_flow/`: hard-timeout releases session and queued tasks continue
- `queue_failed_flow/`: controlled failure releases session and queued tasks continue (trace evidence)
- `queue_budget_exceeded_flow/`: timeout budget exceeded releases session and queued tasks continue
- `reply_dedupe_filler/`: single prompt must not emit multiple fallback replies (idempotent REPLY)
- `telemetry_empty_task/`: regression guard — `cortex.router` empty-task telemetry records must not re-enter DP routing (prevent CLI spam / duplicate LLM calls)

Gates:

- Strong isomorphic gate allow/deny: `docs/evals/traces/isomorphic_gate.json`
- Inject-all gate allow/deny: `docs/evals/traces/inject_all_gate.json`

Notes:

- `telemetry_empty_task/` is expected to run under the **inject-all gate** in CI so non-user records are injected and verified isomorphic.

