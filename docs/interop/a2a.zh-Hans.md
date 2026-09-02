## Agent-to-agent 边界（A2A 风格）— vNext

### 目标

让多 agent 协作具备可扩展性：AdamI 能把任务委派给外部 specialist agents，而不需要在仓库里写一堆定制适配器。
做法是定义一个 **最小、与传输无关** 的消息边界。

### 为什么（2026 趋势）

生态正在收敛到“两层栈”：

- MCP：垂直集成（agent → tools）
- A2A 风格协议：水平协作（agent ↔ agent）

AdamI 已有内部多 agent 编排原语，但需要显式边界以实现互操作。

#### 2026 趋势要点（实用落地）

- 常见的 A2A 任务生命周期包含 `submitted|working|completed|failed|canceled` 等状态，和 AdamI 需要的
  “统一任务生命周期 UX 合约”天然对齐。

### 最小消息 schema（草案）

- `request_id`: string
- `conversation_id`: string（映射到 chat/session/workflow）
- `from_agent` / `to_agent`: agent id
- `kind`: `delegate|handoff|approval_request|approval_result|progress|result|error`
- `task`: string（人类可读任务描述）
- `payload`: object（结构化参数/结果；日志侧脱敏）
- `trace`: 可选 trace_id/span 关联

### vNext 需求

1) **传输抽象**
   - 先做 in-process adapter（便于确定性测试），后续再扩展 HTTP/WebSocket 等。
2) **可观测与审计**
   - 每次 A2A 交换都可追踪，并遵循脱敏策略。
3) **失败语义**
   - 超时、重试、熔断策略明确化。
4) **HITL 兼容**
   - 审批请求可路由到 HITL topic 与 UI 回调。

### 非目标

- 无策略控制的“开放 agent 市场”
- 默认信任外部 agent

