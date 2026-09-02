## MCP interop boundary (vNext)

### Why MCP

In 2026, MCP is the de-facto tool connectivity standard (agent → tools). AdamI already contains MCP plumbing,
but vNext treats it as a **productized boundary**: documented, observable, safe by default.

#### 2026 trend notes (why this matters commercially)

- MCP is increasingly treated as “tool USB-C”: buyers expect a standardized tool interface.
- Production discussions emphasize: **allowlist policy**, **OAuth/identity**, and **observability** at the boundary layer.

### What exists today (v1.0-alpha)

- `src/adami_kernel/mcp/manager.py`: loads server specs and registers tools into:
  - EvolutionEngine tool schemas and dynamic executors
  - ToolboxManager external tool registry (if present)
- Hot refresh: background fingerprint polling triggers rebuild when settings change.

### vNext requirements

#### 1) Safe defaults & policy

- Deny-by-default, allowlist explicit tools (`ADAMI_MCP_ALLOW_TOOLS`).
- Strong timeout policy (`ADAMI_MCP_TIMEOUT_SEC`) and error classification.
- Clear operator docs for secrets and environment variables passed to MCP servers.

#### 2) Observability mapping

Every MCP tool call should emit:

- A trace span: `tool.mcp.call` with attributes:
  - `tool.name`, `mcp.server`, `mcp.tool_name`
  - `status` (`ok|timeout|error`)
- Audit metadata: redacted inputs, response size, latency.

#### 3) Tool discovery & UX

- “What tools are available?” command for operators.
- Surface allow/deny decisions in logs (without leaking tool args).

### Non-goals

- MCP over the public internet without an org policy layer.
- Implicit trust of arbitrary servers; default stance is “treat as untrusted”.

