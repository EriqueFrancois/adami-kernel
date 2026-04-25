# 模块三（Sim）集成边界 — 步骤 0 定稿

本文档固定 **AdamI × simstudioai/sim** 的集成预期与数据边界，供后续步骤（轨迹导出、回放、Webhook、MCP）对齐验收。**不包含**可执行集成代码；代码从步骤 1 起按路线图增量落地。

---

## 1. Sim 是什么（避免期望偏差）

**官方定位（只读调研结论）**

- 仓库：<https://github.com/simstudioai/sim>
- 文档入口：<https://docs.sim.ai/>
- Sim 是**开源可视化 AI Agent 工作流平台**：画布编排（React Flow）、Next.js/Bun、PostgreSQL（pgvector）、可选 Redis/BullMQ、REST/Webhook/定时等触发、大量第三方集成；支持 **MCP** 扩展（见 <https://docs.sim.ai/mcp>）。
- 自托管需关注：Docker Compose 或手动 Bun/Node 栈；环境变量见 <https://docs.sim.ai/self-hosting/environment-variables> 与仓库内 `apps/sim/.env.example`。

**明确不是**

- Sim **不是**专为「第三方内核 EventBus 全量录制 → 离线 pytest 回放」设计的独立仿真引擎。
- 把 Sim 当作「装上去就等于有军演体系」会导致步骤错位；**回放、断言、失败注入的主战场应在 AdamI 仓库内**（见下文轨 B）。

---

## 2. 二轨集成（必须同时写清）

### 轨 A — 产品集成：AdamI 与 Sim（API / Webhook / MCP）

**意图**：在**明确边界**下，让 Sim 作为**外部编排与可视化面**，与 AdamI 通过机器接口对话。

- **REST / Webhook**：按 Sim 文档将「外部事件」或「工作流触发」映射为 HTTP（官方入口：<https://docs.sim.ai/execution>）；AdamI 侧已实现可选 Webhook 桥（步骤 3，`integration/sim/webhook_client.py`）。
- **MCP**：Sim 可连接 MCP Server；AdamI 也可暴露 MCP（与第一、二模块策略一致）。互操作细节在步骤 4 单独设计，**不在步骤 0 实现**。

**谁主谁从（轨 A）**

- **主**：业务上由产品选定——或「Sim 触发 AdamI」，或「AdamI 回调 Sim」；须在具体用例中写清单一方向，避免双主循环争用。
- **从**：另一方仅响应请求、不接管对方全局事件循环。

### 轨 B — 质量工程：AdamI 轨迹格式 + 回放 / 断言（主战场在仓库内）

**意图**：把「运行态才暴露」的问题变成**可版本化的轨迹工件** + **CI 可跑的断言**，不依赖 Sim 是否安装。

- **数据从哪出**：AdamI 内核侧——优先 **EventBus** 上可见的 `AdamiEvent` 流（及与之一致或可关联的 **ExperienceSink / Episode** 事件）。具体 schema 与导出点在步骤 1 定义。
- **到哪止**：导出的 NDJSON（或等价）文件、或 AdamI 内 **Replayer** 的输入边界；可选再 **转发** 到 Sim（轨 A），转发失败**不得**拖垮内核（步骤 3 约定）。
- **谁主谁从**：**AdamI 为主**；Sim 仅为可选消费者或并行编排工具。

---

## 3. 一页说明：数据从哪出、到哪止、谁主谁从（团队对齐用）

**从哪出**

1. **EventBus**（`src/adami_kernel/nexus/bus.py`）：`publish` → 各 `target_topic` 订阅队列；适合作为「全链路神经事件」的单一观测点（步骤 1 中间件或等价机制）。
2. **ExperienceSink / ExperienceAggregator**（`src/adami_kernel/telemetry/experience_sink.py`）：Episode 内 `llm_turn`、`tool_call`、`feedback` 等，已与训练/审计对齐；可能与 Bus 事件**子集重叠**，需在步骤 1.1 **文档化对齐关系**（同 trace 可关联，不要求字节级一致）。

**到哪止**

- **轨 B 必达**：仓库内 **规范化轨迹文件** + **pytest/脚本回放与断言**（步骤 2、5）。
- **轨 A 可选**：Sim 的 API/Webhook 接收端；以 Sim 当前 API 契约为准，AdamI 只做适配层。

**谁主谁从（场景列举，供对齐讨论；实现分步骤完成）**

- 离线回归、发布门禁：**主** AdamI 轨迹 + Replayer；**从** 无（不依赖 Sim）。
- 画布触发 AdamI 能力：**主** 由产品约定（多为 Sim 或网关发起 HTTP）；**从** AdamI 以 HTTP/MCP 处理请求。
- AdamI 推送运行摘要到 Sim：**主** AdamI 适配器 POST；**从** Sim 接收并展示或编排。

---

## 4. AdamI 当前相关实现锚点（只读）

- 事件原语：`src/adami_kernel/nexus/event.py`（`AdamiEvent`）
- 总线：`src/adami_kernel/nexus/bus.py`（`EventBus`、中间件、DLQ）
- 消费入口示例：`src/adami_kernel/core/lifecycle_manager.py`（`system.events` → `DecisionProcessor`）
- 经验轨迹：`src/adami_kernel/telemetry/experience_sink.py`、`experience_aggregator.py`
- 编排：`WorkflowEngine`、`MultiAgentOrchestrator`、`TaskPlanner`（`src/adami_kernel/orchestrator/`）

### 4.1 步骤 1 已落地：EventBus 轨迹 vs Experience Episode（对齐说明）

- **导出位置**：`src/adami_kernel/integration/sim/schema.py`（契约 `ReplayTraceRecordV1` / `adami_replay_trace.v1`）、`trace_sink.py`（队列、批量写 NDJSON；可选转发到 Sim Webhook）。
- **挂钩方式**：`EventBus.initialize()` 在 `SensitiveFilter` 之后注册 **trace 中间件**（始终注册；`ADAMI_SIM_TRACE_EXPORT_ENABLED=false` 时 `offer` 立即返回，不建队列）；**系统事件**走 `publish` 早退分支时 **绕过中间件**，故在同分支开头调用 `offer_trace_event_for_system_path`，保证与业务语义一致且仍脱敏。
- **Episode 对齐**：NDJSON 行的 `episode_id` 取自 `experience_episode_id_ctx`（与 `ExperienceSink` 同上下文时一致）；**ExperienceSink 的 Episode 事件**不自动镜像为 Bus 行，二者为 **子集/可关联** 关系，非字节级一致。
- **配置**：`config.py` 中 `ADAMI_SIM_TRACE_*`（默认关闭；路径空则 `ADAMI_DATA_DIR/traces/eventbus.ndjson`）；`ADAMI_SIM_TRACE_TOPICS_ALLOWLIST` 非空时按 `target_topic` 过滤。

### 4.3 步骤 3 落地：Sim Webhook 桥

- **触发点**：`EventBusTraceSink._flush_batch` 在写本地 NDJSON 成功后，若 `ADAMI_SIM_WEBHOOK_ENABLED` 且配置了 `ADAMI_SIM_WEBHOOK_URL`，则复用同一 `httpx.AsyncClient` 调用 `post_sim_trace_webhook`。
- **载荷**：默认 `envelope`（`schema=adami_sim_webhook.batch.v1` + `records` 数组）；`ndjson_raw` 则与文件相同的 NDJSON 字节流。
- **鉴权**：可选 `ADAMI_SIM_WEBHOOK_SECRET` → `X-Adami-Signature: sha256=<hex>`（对 **最终 body 字节**）。
- **韧性**：网络错误或非 2xx 仅 `warning`，不抛异常、不阻塞 worker 循环。

### 4.4 步骤 4 落地：MCP 互操作（文档 + 桩）

- **文档**：`docs/sim_mcp_bridge.md` — 路径 A（AdamI 作 MCP Server 供 Sim 调用）、路径 B（HTTP 工具网关）；与模块一 allow/deny、模块二 mcp-agent 的协同说明。
- **技术桩**：`integration/sim/mcp_bridge.py`（`SimMcpBridgePath` 枚举）。
- **集成测试占位**：`tests/integration/test_sim_mcp_bridge_e2e.py`，标记 `pytest.mark.integration`；默认 skip，见文内 `ADAMI_SIM_MCP_E2E`。

### 4.5 步骤 5 落地：CI 分层

- **PR / push**：`compliance-and-test`（ruff、pyright、`pytest -m "not integration and not stress"`）；**`replay-traces`** 独立 job，仅黄金回放与步骤 2 验收（PR 合并前须绿）。
- **夜间 / 手动**：`replay-stress`（`workflow_dispatch` 或 UTC 02:00 `schedule`），`pytest -m stress`；可调 `STRESS_REPLAY_ITERATIONS`、`STRESS_FAILURE_THRESHOLD`（默认 0，即任一失败则 job 失败）。

---

## 5. 后续步骤索引

- **步骤 1**：轨迹 schema + EventBus 导出 — **已实现**（见 §4.1）；测试 `tests/test_sim_trace_export.py`。
- **步骤 2**：离线回放骨架与断言 — **已实现**：`src/adami_kernel/integration/sim/replay.py`（`load_ndjson_records`、`validate_phase1_records`、`TraceAssertion` / `replay_inject`）；黄金轨迹 `tests/replay/fixtures/golden_trace.ndjson`；`pytest tests/replay/`；CLI `scripts/replay_trace.py`。
- **步骤 3**：Sim Webhook 桥 — **已实现**：`integration/sim/webhook_client.py`（`post_sim_trace_webhook`，由 `trace_sink` 每批 flush 后调用）；配置 `ADAMI_SIM_WEBHOOK_*`；自托管说明 `docs/sim_self_host_smoke.md`。
- **步骤 4**：MCP 互操作 — **文档 + 桩已实现**：`docs/sim_mcp_bridge.md`、`integration/sim/mcp_bridge.py`；E2E 占位 `tests/integration/test_sim_mcp_bridge_e2e.py`（`pytest.mark.integration`）。
- **步骤 5**：CI 分层 — **已实现**：`.github/workflows/kernel-ci.yml` 与根目录 `ci.yml` 同步；`replay-traces` job 跑 `tests/replay/` + `test_acceptance_sim_step2_replay.py`；主 job 使用 `-m "not integration and not stress"`；`replay-stress` 在 `schedule` / `workflow_dispatch` 下跑 `-m stress`（`tests/stress/test_replay_stress.py`，环境变量 `STRESS_REPLAY_ITERATIONS`、`STRESS_FAILURE_THRESHOLD`）。
- **步骤 6**：删除重复路径、单一事实来源（后期）。

---

## 6. 步骤 0 关键检测（本文档即交付）

- 读者能回答：**Sim 在本集成中的角色**是「可选编排/集成面」+「非专用仿真器」。
- 读者能说出：**轨 A 与轨 B** 各自的主从与数据止点。
- 后续 PR 不得以「Sim 替代 AdamI 内回放」为唯一验收路径。

---

## 7. 参考链接（官方）

- Sim GitHub：<https://github.com/simstudioai/sim>
- Sim 文档：<https://docs.sim.ai/>
- 执行与部署（REST API、Webhook、定时等）：<https://docs.sim.ai/execution>
- MCP（Sim）：<https://docs.sim.ai/mcp>
- 自托管环境变量：<https://docs.sim.ai/self-hosting/environment-variables>

**AdamI 补充**

- 自托管冒烟与 curl 探针：`docs/sim_self_host_smoke.md`
- Sim × MCP 互操作：`docs/sim_mcp_bridge.md`
