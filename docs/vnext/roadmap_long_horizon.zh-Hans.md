## 长期路线图（AGI → ASI 方向）

这份路线图描述 vNext（季度）之后的长期“北极星方向”。它以 `docs/vnext/agi_asi_alignment.zh-Hans.md` 的工程标准为依据，
属于 **方向性规划**，不是短期交付承诺。

> 5 级工程验收标准（可测门禁）见：`docs/vnext/agi_acceptance_levels.zh-Hans.md`。\n

---

## 当前定位（2026-04）与 3–5 年目标

- **当前**：整体仍处在 **Level 1（萌芽与对话者）**，但已具备向更高 Level 演进的一些“成熟原语”（事件总线、工作流骨架、持久化队列、replay 骨架、可观测底座）。\n
- **3–5 年目标**（务实）：\n
  - 稳定达成 **Level 2**（推理可评测、结构化输出可回归、验证循环可审计）；\n
  - 形成通往 **Level 3** 的“工程闭环”（长程自治、错误恢复、预算与取消传播、互操作边界）。\n

下面按能力轨（tracks）给出分阶段规划。\n

---

## Phase 1：可度量自治（第 1–2 个季度）

- **评测作为发布门禁**：golden traces + replay + scoring 成为核心路径必过项。
- **预算全链路落地**：任务级与工具级 time/cost/tool budget，失败语义清晰。
- **统一生命周期合约**：CLI/TG/DC 与外部边界共享同一任务生命周期模型。
- **运维控制面**：pause/cancel/resume + 证据工件（trace id、workflow state snapshot）。

## Phase 2：安全扩容能力（第 2–4 个季度）

- **工具生态扩展**：
  - MCP server 进入“可运营目录”，带 allowlist、信任分级、审计。
  - tool annotations 驱动治理（readOnly/destructive/openWorld → 确认策略）。
- **记忆升级但受治理**：
  - 更丰富的可选检索模式（显式 opt-in）+ 默认 citations
  - 摄入消毒 + 不可信内容标记
- **Agent 专业化**：
  - 外部 specialist agent 通过 A2A 边界接入
  - 内部角色 agent 模块化，并绑定评测套件

## Phase 3：自我改进闭环（年级别）

- **经验蒸馏**：
  - 自动把失败簇沉淀为 policy/template/test
  - “学习产物”版本化并可审计
- **自动化安全回归**：
  - 对抗性测试包：prompt injection、密钥泄露、工具滥用
- **元优化**：
  - 系统可以提出改动，但晋升需通过评测门禁与显式审批

---

## 3–5 年开发计划（按能力轨）

> 说明：每一轨都必须产出可验收工件（golden traces / replay / scorecards / fault suite / 审计证据）。\n

### Track A：评测与回归（Learning that compounds）

- **0–12 个月（L1→L2 前置门槛）**\n
  - 扩大 `docs/evals/traces/` 覆盖：planner 主通路、工具失败/超时、cancel 传播、队列恢复、写入/检索引用。\n
  - scorecards 形成硬门槛：correctness / operability / UX-noise / safety。\n
- **12–24 个月（L2 达标）**\n
  - 引入 verifier traces：验证结果可结构化评分，形成“推理可评测”。\n
- **24–60 个月（L3 前置门槛）**\n
  - fault suite 工业化：网络抖动、429、API schema drift、MCP server 异常；恢复率指标写入门禁。\n

### Track B：生命周期合约与自治控制（Autonomy with bounded risk）

- **0–12 个月**\n
  - 统一跨端生命周期：queued/started/running/done|timeout|cancelled 的用户可见与可观测一致。\n
  - 预算与取消传播：planner→workflow→tools 全链路；hard-timeout 必定释放会话并继续队列。\n
- **12–24 个月（L2→L3 前置）**\n
  - checkpoint/resume：长任务可中断续跑（含外部中断与进程重启恢复）。\n
- **24–60 个月（L3 达标）**\n
  - 48h+ 长程自治（仿真）通过 fault suite；具备回滚、重试策略版本化。\n

### Track C：工具与 Agent 互操作边界（MCP + A2A）

- **0–12 个月**\n
  - MCP 成为一等边界：allow/deny、超时、审计元数据、可观测 span 映射。\n
  - A2A 最小消息 schema：委派/交接/审批/结果，传输无关。\n
- **12–24 个月（L3 前置）**\n
  - 角色化 agent（planner/executor/reviewer/debugger）模块化，可插拔，并绑定评测套件。\n
- **24–60 个月（L3 达标）**\n
  - 外部 specialist agent 接入无需修改 DP 核心；能力通过边界层扩展且可审计。\n

### Track D：记忆治理与引用（World model & governance）

- **0–12 个月**\n
  - 写入纪律：来源、去重键、风险等级、为何写入；摄入抗注入。\n
  - 检索默认带引用（路径/ID），回答可审计。\n
- **12–24 个月（L2 达标）**\n
  - 记忆污染控制 + 可信分层；长上下文与外部记忆组合回归可测。\n
- **24–60 个月（L3 前置）**\n
  - 任务级“世界状态”模型：把关键中间状态持久化为可恢复 checkpoint。\n

### Track E：安全与运维（Safety as a system property）

- **0–12 个月**\n
  - 高风险操作 HITL 默认开启；全链路脱敏与审计记录。\n
  - CLI/端口噪音门禁：busy/queued/toast 风格一致。\n
- **12–24 个月（L3 前置）**\n
  - 沙箱默认：文件/网络/命令执行最小权限；策略可配置。\n
- **24–60 个月（L3 达标）**\n
  - 混沌工程式回归：节点崩溃、数据损坏、算力切断下保持核心功能连续。\n

## “ASI”意味着什么（需要的护栏）

即使能力加速，内核必须长期保持：

- **人类可覆盖** 与 权限边界
- **可审计性**（谁/何时/为何/调用了什么）
- **可度量安全**（脱敏/沙箱/策略强制）

