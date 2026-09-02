## vNext 路线图（一个季度）— AdamI 内核升级

本路线图以 **实用 Agent 的可落地性** 与 **可度量的复利演进** 为核心，同时对齐 2026 生态趋势（**MCP**、agent 互操作、评测/可观测纪律）。

审计报告：`docs/audit/v1_0_alpha_audit.zh-Hans.md`  
AGI/ASI 工程标准（北极星）：`docs/vnext/agi_asi_alignment.zh-Hans.md`  
AGI 5 级工程验收标准（门禁）：`docs/vnext/agi_acceptance_levels.zh-Hans.md`  
长期（3–5 年）路线图（方向）：`docs/vnext/roadmap_long_horizon.zh-Hans.md`

---

## vNext 指导原则

- **评测先于能力扩张**：新增能力必须可被评测与回归验证（golden traces + replay + scoring）。
- **一套任务生命周期合约**：CLI / Telegram / Discord 统一 queued/running/done 语义，减少噪音。
- **互操作边界就是产品特性**：工具与外部 specialist agent 能“插拔式接入”，不靠定制适配。
- **AGI 成熟度标尺**：每个里程碑都要推进可度量自治、学习闭环、安全与互操作（见 `agi_asi_alignment`）。

### 当前定位与 Level 映射

- **当前定位**：我们仍处在 **Level 1（萌芽与对话者）**。\n
- **季度目标**：vNext 的 A/B/C 里程碑主要在补齐 **Level 2/3 的工程前置门槛**（评测门禁、生命周期合约、预算与取消传播、互操作边界）。\n

---

## 里程碑 A（第 1–4 周）：可靠性 + 生命周期 UX 合约

### 交付物

1) **任务生命周期 UX 合约**

- 状态：`queued` → `started` → `running` → `done|failed|timeout|cancelled`
- 至少一条 operator 可见消息包含 `trace_id`（必要时包含 `workflow_id`）
- 渠道规则：
  - Telegram：避免聊天刷屏，优先 toast + 单条进度消息 + 最终结果
  - Discord：能用 ephemeral 就用（排队确认不污染频道）
  - CLI：提示符干净；一行状态 + 明确队列位置

2) **超时预算模型（Timeout budget）**

- 保留 hard-timeout（`ADAMI_CLI_TASK_HARD_TIMEOUT_SEC`、`ADAMI_TASK_HARD_TIMEOUT_SEC`）
- 增加：每次工具调用（web/MCP/LLM）的子超时与明确错误分类（budget exceeded）
- 形成“取消传播”约定（best-effort 清理，不影响主循环）

3) **队列健康工具**

新增命令（CLI + 文本命令）：

- `/queue status`：pending 数、in-progress 时长、最老 pending 时长
- `/queue cancel`：取消当前任务
- `/queue discard`：清空 pending + in-progress
- `/queue export-trace`：导出最近 trace_id/路径

> 进度（已落地一部分并接入评测门禁）：  
> - `queue_status` / `queue_timeout_flow` / `queue_discard` 已加入 `docs/evals/traces/` 并通过 suite eval；  
> - `queue_status`、`queue_timeout_flow`、`queue_discard` 已加入强同构门禁 allowlist（`isomorphic_gate.json`）。

4) **配置旋钮（在设置向导中暴露）**

- `ADAMI_CLI_TASK_HARD_TIMEOUT_SEC`、`ADAMI_TASK_HARD_TIMEOUT_SEC`
- `ADAMI_TASK_QUEUE_TTL_SEC`、`ADAMI_TASK_QUEUE_IN_PROGRESS_TTL_SEC`
- `ADAMI_EVENT_CONSUMER_MAX_CONCURRENT`

### 验收标准

- 任一卡住的工具调用不会超过 hard-timeout 阻塞队列。
- 用户始终能分辨“已入队/正在跑/已完成”。
- Telegram 不出现“敷衍刷屏”回归（单测 + 场景测试覆盖）。
- **事件隔离**：`system.events` 上的内部遥测/系统事件不得重新进入用户意图主通路（例如缺失 `payload.task` 的事件必须被过滤）；并有回归测试覆盖。
- **幂等性**：对同一用户输入（同 `chat_id` + `trace_id`），低信息系统提示（busy/queued/timeout/cancelled）最多发送一次，避免重复消费/重入导致刷屏。

### Level 映射（北极星门禁）

- **Level 1 → Level 1 完整性**：消除刷屏/回声重入/队列语义歧义；保证单次输入最多一条关键用户可见输出。\n
- **Level 2 前置**：预算与取消传播可观测（timeout/cancel 有证据工件与稳定回归）。\n

---

## 里程碑 B（第 5–8 周）：评测与回放骨架升级（复利引擎）

### 交付物

1) **Golden traces**

在 `docs/evals/traces/`（或本机 `.adami_data/traces/`）建立小而精的轨迹集：

- `/report run daily`（报告生成）
- `/intake`（知识摄入）
- planner → workflow engine（工作流主通路）
- 工具失败/超时路径
 - （新增）LLM 调用、web_search、MCP external tool、多轮 toolchoice、planner 多分支（含 rollback）

2) **Replay runner（开发者可用）**

把现有 `src/adami_kernel/integration/sim/replay.py` 从“校验”升级为“评测”：

- 稳定 mock：LLM/web/MCP
- 断言包（topic/顺序/payload 形状）
- 评分摘要（pass/fail + 原因 + 最小指标：latency/cost/noise）
 - （新增）强同构校验：`--verify-isomorphic`
 - （新增）全量注入回放：`--inject-all-records`
 - （新增）Phase 3 故障注入：`--faults faults.json`（产出 faulted trace + eval 报告）

3) **质量计分卡（scorecards）**

- correctness / safety / operability / UX / latency / cost
- CI 中加入“无回归”门禁
 - （新增）operability 作为硬门槛（`min_operability`）
 - （新增）compare 门禁支持阈值：`--max-score-drop` / `--max-dim-drop`
 - （新增）compare-refs 跨代兼容：baseline ref 不可评估时降级为“新增能力展示”（markdown 顶部提示）

### CI 门禁建议

- 继续保留现有 pytest 全套门禁
- 新增 replay gate：跑一组 golden traces（mock 模式）并产出 artifact 报告

### 验收标准

- 每个 PR 都能在本地与 CI 稳定跑 replay suite。
- 能用同一套 traces 对比 baseline/head 的行为差异（baseline 可为 merge-base 或旧 tag；旧 tag 不具备 eval CLI 时自动降级为“新增能力展示”）。

### Level 映射（北极星门禁）

- **Level 2 前置**：推理/执行行为必须可回放、可打分、可对照；验证循环的引入必须有 scorecard 约束。\n

---

## 里程碑 C（第 9–12 周）：互操作扩展（MCP + agent-to-agent 边界）

### 交付物

1) **MCP 作为一等工具边界**

- 文档化配置、allow/deny 策略、超时行为
- 可观测映射：每次 MCP 工具调用出 trace span + 结构化审计元数据
- 安全默认：deny-by-default（除非显式 allowlist）

2) **A2A 风格 agent-to-agent 边界**

- 最小消息 schema（委派/交接/结果/审批）
- 传输抽象（先 in-process，后续可 HTTP/WebSocket/queue）

### 生态对齐（2026）

- 互操作按层叠加而非互斥：**MCP（tools）+ A2A 风格（agents）**
- **边界层必须自带可观测**，让买方能审计“谁在何时为何调用了什么”

### 互操作配置旋钮

- MCP：`ADAMI_MCP_ENABLED`、`ADAMI_MCP_SERVERS_JSON`、`ADAMI_MCP_ALLOW_TOOLS`、`ADAMI_MCP_DENY_TOOLS`、`ADAMI_MCP_TIMEOUT_SEC`

### 验收标准

- 可按文档接入第三方 MCP server，并产出可追踪/可审计的工具调用。
- 可接入外部 specialist agent 而无需修改 `DecisionProcessor` 核心逻辑（仅经由边界层）。

### Level 映射（北极星门禁）

- **Level 3 前置**：工具与 agent 的边界标准化 + 策略 + 可观测；为长程自治的错误恢复与审计提供基础设施。\n

---

## 本季度范围外（明确不承诺）

- 企业级身份体系（SSO/SCIM）与完整多租户控制平面
- 计费/用量计量（超出基础 observability counter 的部分）
- “AGI 宣称”——聚焦可度量的自治、学习闭环、安全与互操作

