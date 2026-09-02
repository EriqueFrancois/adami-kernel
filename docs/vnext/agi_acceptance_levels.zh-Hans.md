## AGI 北极星工程验收标准（Level 1–5）— AdamI

本文把“AGI/ASI 成熟度”拆成 **可工程化、可回归、可审计** 的 5 级验收标准。\n
定位：\n
- `docs/vnext/agi_asi_alignment.zh-Hans.md` 负责“方向与原则”（为何做、做对什么算对）。\n
- 本文负责“**验收与门禁**”（做到什么程度算达标、如何用测试证明）。\n

> 约定：每一条“验收标准”都必须能落到至少一种可运行工件：pytest、replay suite（`adami-replay-eval`）、golden traces、或 fault injection 评测报告。\n

---

## 统一术语与可观测要求（所有 Level 共同适用）

### 任务生命周期合约（跨 CLI / Telegram / Discord）

- 状态：`queued → started → running → done|failed|timeout|cancelled`\n
- 取消语义：用户发出取消后，系统 **必须 best-effort 传播取消**，并 **释放会话占用**，让队列继续。\n
- 超时语义：达到 hard-timeout 必须释放会话占用，并给出用户可见说明。\n

### 必备可观测信号（最小闭环）

- **trace_id**：每个用户可见交付（至少一条消息）需携带可追踪标识。\n
- **事件来源隔离**：内部遥测事件（如 router/tool spans）不得再次进入用户意图主通路。\n
- **replay 可比对**：同一套 traces 能对比 baseline/head 行为差异。\n

---

## Level 1：萌芽与对话者（Emerging / Chatbots）

### 定义

能力持平普通人；能够进行自然语言对话；系统以“请求-响应”为主，状态弱、依赖外部记忆与上下文拼接。

### 工程本质（架构签名）

- 主路径为 **Intent Router / Prompt Builder / LLM** 的序列生成。\n
- 状态以 chat 维度的 **轻量 session lock + 持久化队列** 管理，确保不因单次任务卡死。\n

### 功能验收（可测指标）

- **上下文维持**：在固定窗口（例如 128k token 的提示构建策略）下，多轮对话事实召回率 Recall ≥ 95%。\n
- **指令遵循**：在标准提示词约束下，JSON / Markdown 等格式输出解析失败率 ≤ 2%。\n
- **无刷屏**：忙/排队/超时等低信息回复在同 chat 下被节流（跨平台一致）。\n
- **无回声重入**：内部遥测事件不进入意图路由（例如 `system.events` 上无 `payload.task` 的事件不得触发 `DecisionProcessor`）。\n

### 必需 instrumentation

- 事件消费日志包含：`trace_id/source_module/chat_id/task`。\n
- 关键状态转移：`queued/started/running/done|timeout|cancelled` 可被 replay trace 捕获。\n

### 标准测试套件（必须可自动化）

- **Single prompt, single reply**：输入一行 `你好`，用户可见回复 **最多 1 条**。\n
- **Queue UX**：`/queue status|cancel|discard|export-trace` 在三端一致，且 i18n parity 通过。\n
- **Telemetry isolation**：向 `system.events` 注入 `source_module=cortex.router` 且 `payload.task=''` 的记录，不得触发 DP 主路由。\n

### Exit gate（硬门禁）

- 50+ 条 golden traces（覆盖：Direct Answer、planner、工具失败、busy/queued/timeout/cancel）在 replay suite 下稳定通过；\n
- `tests/test_i18n_locale_key_parity.py` 必须绿色。\n

---

## Level 2：胜任与推理者（Competent / Reasoners）

### 定义

在 **单一任务** 中达到专业人士的可用水平（目标：可持续 ≥ 50% 专家水准），能处理博士级复杂推理问题，并能在输出前自纠错。

### 工程本质（架构签名）

引入 System 2：**生成-验证循环（Verifier-Generator Loop）**，但验证必须是“可回放可审计”的工程机制，而不是依赖不可控的隐式链路。

### 功能验收（可测指标）

- **隐式多步推理**：无外部工具时，对复杂逻辑问题输出可复现的推理结论，并具备自我纠错（同一输入多次运行，通过率显著高于 Level 1）。\n
- **结构化输出稳定**：复杂 schema 一次通过率显著提升（如 50 变量配置一次性过 schema）。\n
- **推理可评测**：推理过程可被评价（以 scorecards 形式），至少覆盖 correctness / hallucination risk / completeness。\n

### 必需 instrumentation

- **Verifier 输出**必须结构化（例如：验证结论、失败原因、建议修复），并写入 trace 记录。\n
- replay suite 支持对 verifier/solver 两段分别打分。\n

### 标准测试套件

- **Static deadlock reasoning**：输入一段存在深层死锁的代码，不运行代码，仅静态推理指出死锁路径并给出重构方案。\n
- **SWE-bench Lite（或等价内核任务集）**：以“修复 + 测试通过”为准的 Pass@1 达到预设阈值（用 scorecard 门禁表达）。\n

### Exit gate

- 引入“可回放验证器”后，相关 traces 的 correctness score 不低于 baseline，且噪音/成本不显著回归。\n

---

## Level 3：专家与智能体（Expert / Agents）— 工程架构分水岭

### 定义

在多数任务中达到 90% 专家水平，能够代表用户执行长达数天的复杂任务；从“思考器”转为“行动器”。

### 工程本质（架构签名）

- **多智能体编排（Multi-agent orchestration）** + **工作流引擎（Workflow Engine）** 成熟；\n
- 具备 **长程自治**：DAG 计划、checkpoint、重试/回滚、错误自修复、预算约束。\n

### 功能验收（可测指标）

- **48h+ 自治（仿真）**：在 replay + fault injection 环境下，持续运行超过 48 小时，不崩溃、不陷入死循环。\n
- **错误恢复率**：工具/API 失败的恢复率 ≥ 85%（定义需落到 fault suite 报告）。\n
- **人类可控性**：任何时刻可 cancel/pause，并可从 checkpoint 续跑。\n

### 必需 instrumentation

- 工作流节点事件：start/finish/fail/retry/rollback。\n
- tool calls 具备审计元数据（谁、何时、为何调用了什么）。\n

### 标准测试套件

- **CVE patch PR（受限权限）**：拉取 repo、定位漏洞、写补丁、跑测试、生成 PR（至少产出可复核补丁与说明；提交与 PR 可视权限配置）。\n

### Exit gate

- fault suite 覆盖：网络抖动、超时、429、API schema 变更、工具 crash；并形成可对比 scorecards。\n

---

## Level 4：大师与创新者（Virtuoso / Innovators）

### 定义

达到 99% 人类顶尖水平，能够在约束下自主产生新知识/新工具，并通过实验框架验证；技能可泛化并持久化复用。

### 工程本质（架构签名）

- **自演进技能循环**：发现短板 → 生成/改造技能 → 测试验证 → 注册 → 后续复用。\n
- 具备可度量的“能力增长曲线”，并能在回归门禁下安全推进。\n

### 功能验收（可测指标）

- **从零到一的可验证假设**：提出假设并在 sandbox/仿真环境验证，产出可复现报告。\n
- **技能泛化**：一次学习后，在新但相似分布任务上复用成功率显著提升。\n

### 必需 instrumentation

- 每次技能生成必须绑定：来源数据、测试覆盖、风险等级、回滚策略。\n

### 标准测试套件

- **Invent tool → test → register → reuse**：四段 traces 连续通过，并且 reuse 阶段依赖已注册技能成功完成任务。\n

---

## Level 5：超人与组织者（Superhuman / Organizations）

### 定义

在认知与执行任务上形成“组织级系统之系统”，可在高权限基础设施上进行全局调度优化，并具备混沌工程级生存力。

### 工程本质（架构签名）

- IaC 自治、资源调度、组织运营闭环。\n
- 多租户治理、合规审计、强隔离与强可控。\n

### 验收方向（仍需工程化表达）

- **战略→战术**：把抽象意图分解为可执行组织动作与系统变更，并可被审计。\n
- **混沌生存力**：节点瘫痪、数据污染、算力切断下保持核心功能连续。\n

### Exit gate（长期）

- 在受限且合规的模拟环境里完成“公司运营闭环”任务，产出可审计资产、并满足安全与合规门禁。\n

