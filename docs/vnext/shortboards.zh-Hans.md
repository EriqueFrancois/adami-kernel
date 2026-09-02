## vNext 关键短板清单（按优先级）— 阻塞“实用 Agent”的因素

这是面向 **实用 Agent 内核** 的“缺什么最致命”清单，每条都带可验收标准，保证推进可度量。

参考：`docs/audit/v1_0_alpha_audit.zh-Hans.md`、`docs/vnext/roadmap.zh-Hans.md`

---

## 1) 评测与回放（first-class）— 质量回归体系

**问题**：没有行为评测，就无法可信地“自进化”，也无法快速迭代。

**验收标准**

- 有一组 golden traces，可在本地与 CI 运行。
- 回放输出确定性报告：断言 pass/fail + 指标摘要（latency/cost/noise）。
- PR 能证明核心场景无回归（report/intake/workflow/tool failure）。

推荐目录：`docs/evals/README.zh-Hans.md` 与 `docs/evals/traces/…`。

---

## 2) 统一任务生命周期 UX 合约（不乱、不刷屏）

**问题**：多通道 Agent 失败的首因往往是用户看不懂“到底在跑还是没跑”，以及被敷衍消息刷屏。

**验收标准**

- 所有通道统一状态：`queued|started|running|done|failed|timeout|cancelled`。
- 每个任务至少一次展示 `trace_id`（必要时展示 `workflow_id`）。
- Telegram/Discord 默认链路最多：
  - 1 次排队确认（toast/ephemeral 优先），1 条进度消息，1 条最终结果。

---

## 3) 工具边界产品化（MCP）

**问题**：MCP plumbing 已有，但要“可卖/可用”必须补齐文档、策略、观测、默认安全。

**验收标准**

- 有完整文档指导接入 MCP（含 allow/deny、超时、错误分类）。
- 每次 MCP 工具调用都有 trace span（`tool.mcp.call`）与结构化审计元数据（脱敏参数、耗时）。
- 运维可列出当前可用 MCP 工具，并看见 allow/deny 是否生效。

---

## 4) Agent-to-agent 互操作（A2A 风格边界）

**问题**：内部多 agent 有了，但外部 specialist agent 很难“插拔式接入”。

**验收标准**

- 有最小消息 schema（委派/交接/结果）并文档化。
- 有传输抽象（先 in-process，便于确定性测试）。
- 每次 A2A 交换都可追踪并遵循脱敏。

---

## 5) 记忆质量（检索 + 引用 + 写入治理）

**问题**：当前 SecondBrain 检索刻意保守（安全/性能边界），但会限制实用性上限。

**验收标准**

- 提供可选检索模式：
  - 默认：当前保守模式
  - 可选：更深检索（显式 opt-in，范围受控，性能有上限）
- 任何引用记忆的回答都带轻量 citation（路径/笔记 id）。
- 记忆写入有治理（provenance、dedupe、避免 secrets）。

---

## 6) 运维加固（策略 profile + 自检 + 证据工件）

**问题**：生产落地需要“系统到底强制了什么”的清晰答案。

**验收标准**

- `self-check` 报告汇总：沙箱可用性、脱敏开关、MCP allowlist、OTel exporter、队列与超时配置。
- 有 safe mode：禁用外部工具，仅本地运行用于事故响应。

