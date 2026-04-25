# AdamI Kernel（亚当内核）

## 项目口号（Tagline）

**面向分布式数字有机体的工业级事件微内核 —— 记忆可持久、工作流可审计、感官不阻塞中枢。**

AdamI 不是「单模型 API 薄封装」，而是面向**长周期智能体运行时**：多源感官汇入类型化事件总线，由生命周期管理器以**有界并发**消费决策，编排层持久化 DAG 状态，使运维可在重启与审计下延续。

---

## 受众

- **初级开发者 / 集成方**：读完本文后转向 [API_REFERENCE.md](API_REFERENCE.md) 与根目录 [README.md](../../../README.md)。
- **媒体与分析师**：本文 + [WHITEPAPER.md](WHITEPAPER.md) 用于定位；技术深度以 [ARCHITECTURE.md](ARCHITECTURE.md) 为准。
- **买方技术初筛**：用 [ARCHITECTURE.md](ARCHITECTURE.md)、[SECURITY.md](SECURITY.md) 对照 `src/adami_kernel/` 开源树核验表述。

---

## 仿生学特性（可视化对照）

| 仿生隐喻 | 软件对应 | 职责 |
|----------|----------|------|
| **周围神经系统（Nexus）** | `nexus/` — CLI、Telegram/Discord、`EventBus` | 感知接入、发布 `AdamiEvent`、健康检查与 DLQ |
| **大脑皮层（Cortex）** | `cortex/` — 路由、意图、`DecisionProcessor`、提示词与工具 | 推理、路由、向 Planner 委托复杂任务 |
| **海马体（Hippocampus）** | `hippocampus/` — `LayeredMemory`、情节记忆、巩固 | SQLite 工作流状态 + 追加式经验 |
| **昼夜节律 / 脏器** | `peripheral/` — 如定时训练、Report Studio | 节律性维护与对外产出物 |
| **免疫系统** | `guardian/` + 技能加载/清洗 | AST 审计、脱敏、沙箱执行策略 |

---

## 快速启动

### 内核（Python）

```bash
poetry install
poetry run adami
```

- **日志**：`.adami_data/kernel.log`（轮转策略见 `config.py`）。
- **持久化 L2 记忆**：`.adami_data/l2_memory.db`。
- **密钥**：仅放 `.env`；参见 `.env.example`。

### Web 控制台（可选）

```bash
cd frontend
npm install
npm run dev
```

---

## 「性能」的工程含义

AdamI 优先优化**运行韧性**，而非单一合成基准分数：

- **认知侧背压**：`LifecycleManager` 以可配置的 **asyncio 信号量**（`ADAMI_EVENT_CONSUMER_MAX_CONCURRENT`）消费 `system.events`，抑制 `create_task` 风暴。
- **可审计性**：`WorkflowEngine` 经 `LayeredMemory` 持久化 `WorkflowState`，暂停/恢复与事后分析为一等公民。
- **故障隔离**：事件总线 **DLQ** 与中间件链（敏感信息过滤 + 追踪下沉）降低单点提供商/工具异常的影响半径。

更多模块 SLA 与运维手册见仓库 `docs/`（双机同步、DeerFlow 桥安全、i18n 策略等）。

---

## 后续文档

- **架构**：[ARCHITECTURE.md](ARCHITECTURE.md)
- **商业白皮书**：[WHITEPAPER.md](WHITEPAPER.md)
- **API 参考**：[API_REFERENCE.md](API_REFERENCE.md)
- **安全**：[SECURITY.md](SECURITY.md)
- **贡献指南**：[CONTRIBUTING.md](CONTRIBUTING.md)

---

## 许可与署名

以仓库内 `LICENSE`、`pyproject.toml` 为准。本文档包描述**当前**开源布局；部署侧调参应写入私有 Runbook。
