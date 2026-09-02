## Agent-to-agent boundary (A2A-style) — vNext

### Goal

Make multi-agent collaboration extensible: AdamI should delegate to external specialist agents
without bespoke in-repo adapters, by defining a minimal, transport-agnostic message boundary.

### Why (2026 trend)

The ecosystem is converging on a two-layer stack:

- MCP: vertical integration (agent → tools)
- A2A-like protocols: horizontal coordination (agent ↔ agent)

AdamI already has internal multi-agent orchestration primitives, but needs an explicit boundary to interoperate.

#### 2026 trend notes (practical framing)

- The common production architecture is a **two-layer stack**:
  - MCP for vertical tool integration
  - A2A-like protocols for horizontal agent coordination
- A2A-style lifecycles typically include first-class states like `submitted|working|completed|failed|canceled`,
  which aligns with AdamI’s need for a unified task lifecycle contract across channels.

### Proposed minimal schema (draft)

- `request_id`: string
- `conversation_id`: string (maps to chat/session/workflow)
- `from_agent` / `to_agent`: string ids
- `kind`: `delegate|handoff|approval_request|approval_result|progress|result|error`
- `task`: string (human-readable)
- `payload`: object (structured args/results; redacted for logs)
- `trace`: optional trace_id/span linkage

### vNext requirements

1. **Transport abstraction**
   - Start with in-process adapter (for tests), then add HTTP/WebSocket later.
2. **Observability & audit**
   - Every A2A exchange is traced and logged with redaction.
3. **Failure semantics**
   - Timeout, retry policy, and circuit breakers are explicit.
4. **HITL compatibility**
   - Approval requests can be routed through HITL topics and UI callbacks.

### Non-goals

- “Open agent marketplace” without policy controls.
- Automatic trust of external agents.

