<p align="center">
  <img src="./20260328_Adami_workflow.png" alt="AdamI Logo" width="220" />
</p>

<p align="center">
  <strong>AdamI：人类与 AI 一体化的自进化 Agent 协作引擎</strong>
</p>

> English README: `README.md`

## Why AdamI（痛点）

Multi-Agent 系统在真实落地时常见的痛点是“能跑 Demo，但难以规模化复用与治理”。AdamI 聚焦解决：

- **协作失控**：多个 Agent / 工具链并行后，任务边界不清、状态分散、重试/回滚困难。
- **工作流不可复用**：一次性 prompt/脚本多，难以沉淀成可版本化、可审计、可演进的能力单元（skills/workflows）。
- **本地与云混搭复杂**：本地 LLM、远程 LLM、Web 工具、消息通道（Telegram/Discord/CLI/Web）在工程上难以统一。
- **上线可观测性不足**：缺少一致的指标/追踪/日志策略，难以做 SLO、失败率与重试治理、审计与脱敏合规。

## Key Features（核心特性）

- **[Evolve] 自进化技能循环**：从执行与回放中沉淀经验，推动技能/工作流迭代，降低人工维护成本。
- **[Workflow] 可视化工作流与可恢复执行**：以 DAG 形式编排与执行，支持暂停/恢复/审计与持久化状态。
- **[Local LLM] 本地 LLM 支持**：兼容本地推理与远程模型调用，便于隐私与成本控制。
- **[Multi-Channel] 多通道交互**：CLI / Web / Telegram / Discord 统一接入同一事件与执行路径。
- **[Obs] 生产级可观测性**：OpenTelemetry traces + metrics，支持采样策略与导出脱敏策略，便于商业部署。

## Quick Start（<= 3 步）

```bash
poetry install
poetry run adami
```

### 首次初始化（工业级严格必填）

首次运行时，AdamI 会在未完成初始化前**拒绝启动**。你需要通过 CLI 初始化向导依次完成：
语言 → 运行模式 → 本地 LLM（必需兜底）→ 云端 Key（至少一个必需）→ Telegram/Discord（至少一个必需）→ 可观测性。

向导会把配置写入本地覆盖文件（加载顺序晚于 `.env`）：

- 默认：`.adami_data/cli_overrides.env`
- 自定义路径：`ADAMI_CLI_ENV_FILE=/path/to/cli_overrides.env`

需要重新初始化时，删除该覆盖文件（或把其中 `ADAMI_FIRST_RUN_COMPLETE=false`），再运行 `poetry run adami`。

## Architecture（多 Agent 编排）

```mermaid
flowchart TB
  subgraph Inputs[Inputs]
    CLI[CLI]
    WEB[Web Console]
    TG[Telegram]
    DC[Discord]
  end

  Inputs --> EB[EventBus]
  EB --> LM[LifecycleManager\n(bounded concurrency)]
  LM --> DP[DecisionProcessor\n(intent routing)]
  DP -->|simple/known| Templates[Intent Templates\n(optional tiers)]
  DP -->|complex| Planner[Planner\n(plan + execute)]
  Planner --> Composer[SkillComposer\n(build DAG)]
  Composer --> Engine[WorkflowEngine\n(execute DAG)]
  Engine --> Memory[LayeredMemory\n(persist state/experience)]
  Engine --> Tools[Tools / Skills\n(WebTool, LLM, Sandboxes, ...)]

  Engine --> Obs[Observability\n(OTel traces/metrics)]
  DP --> Obs
  LM --> Obs
```

## Enterprise / Cloud（商业版）

- **Enterprise**：私有化部署 / 定制化集成 / 合规支持
- **Cloud**：托管版 AdamI（SaaS）

联系入口：见 `COMMERCIAL_LICENSE.md`。

