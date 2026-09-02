## AdamI v1.0.0-alpha — 审计（面向“实用 Agent 内核”）

**范围**：以“可落地、可运营”的 Agent 内核为标准，对 `v1.0.0-alpha` 做能力审计与短板分析。  
这不是渗透测试；所有结论以仓库源码与文档为依据。

### 主要审阅资料（第一手）

- 产品承诺：`README.md`、`CHANGELOG.md`
- 技术边界：`docs/standard/zh/ARCHITECTURE.md`、`docs/standard/en/WHITEPAPER.md`
- 关键模块（抽样）：
  - `src/adami_kernel/core/lifecycle_manager.py`（有界并发 + 生命周期粘合层）
  - `src/adami_kernel/cortex/decision_processor.py`（路由 + 会话锁 + 队列自动 drain）
  - `src/adami_kernel/core/task_queue.py`（每 chat FIFO 持久化 + TTL/caps）
  - `src/adami_kernel/mcp/manager.py`（MCP server/tool 注册）
  - `src/adami_kernel/integration/sim/replay.py` + `replay_cli.py`（轨迹校验/回放骨架）
  - `src/adami_kernel/observability/*`（OTel 策略 + 活跃度时钟 + 信使指标）

---

## 1) 能力映射（审计维度 → 当前状态）

### 可靠性（有界并发、生命周期、恢复）

- **`system.events` 有界并发**：**已具备**  
  - `LifecycleManager` 使用 `asyncio.Semaphore` 做并发上限（`ADAMI_EVENT_CONSUMER_MAX_CONCURRENT`）。
- **每 chat 会话锁**：**已具备**  
  - `DecisionProcessor` 用 `session_locks[chat_id]` 串行化每个 chat 的执行，忙时转入队列。
- **每 chat FIFO 队列 + 持久化**：**已具备**  
  - `TaskQueueStore` 持久化到 JSON；支持 pending TTL/caps，支持可选 Fernet 静态加密。
- **hard-timeout 防止“占锁卡死”**：**已具备**  
  - CLI hard-timeout + 非 CLI hard-timeout；超时会释放锁让队列继续 drain。
- **重启后的 in-progress 恢复**：**部分具备**  
  - 队列记录 `in_progress`；提供 `recover_in_progress_to_front` + “stale in-progress TTL”。  
  - 缺口：缺少结构化 checkpoint 来在 tool-call 中途安全续跑。
- **取消语义（Cancellation）**：**部分具备**  
  - `asyncio.wait_for` 触发取消，但向下传播到工具调用的“可控/可清理”并不一致。  
  - 缺口：需要统一的 budget 模型与结构化取消处理约定。

### 可用性（上手、设置、可预测）

- **首次运行 fail-fast 初始化**：**已具备**
- **配置向导 + 本地 overrides 持久化**：**已具备**（写入 `.adami_data/cli_overrides.env`，支持 reload）
- **噪音控制（避免“敷衍回复”）**：**在改善**  
  - filler 检测存在（`port.detection.filler_phrases`），但目前偏“记录为主”。  
  - 缺口：需要统一的“任务生命周期 UX 合约”，让 CLI/TG/DC 都能稳定表达 queued/running/done。

### 能力（工具、工作流、多 Agent、记忆）

- **工作流引擎 + DAG 状态持久化**：**已具备**
- **多 Agent 编排**：**内部具备** / **对外互操作边界缺失**  
  - 内部编排组件存在，但缺少对外 agent-to-agent 标准边界。
- **Report Studio**：**已具备**（`/report` 产出 SecondBrain 可运营工件）
- **记忆**：SecondBrain PARA 树 **已具备**；检索能力 **部分具备**  
  - 当前检索刻意做了范围约束（关键词、部分目录、浅层），适合安全/性能边界。  
  - 缺口：实用 Agent 需要更强可选检索 + 引用/citation 纪律。

### 安全（脱敏、沙箱、密钥）

- **总线脱敏中间件**：**已具备**（以安全/架构文档为准）
- **技能审计/洗髓**：**已具备**（静态门闩存在；细节见安全文档）
- **Docker 沙箱（可选）**：**已具备**  
  - 缺口：需要更清晰的“策略 profile”与 operator 自检输出，明确生产到底强制了什么。

### 可运维（可观测、回放、调试）

- **可观测性（OTel 策略）**：**已具备**（采样/导出脱敏 + 信使指标钩子）
- **回放/轨迹校验**：**已有骨架**  
  - 当前 replay 更偏“schema 校验 + inject 骨架”；  
  - 缺口：升级成“golden traces + scoring”的行为评测体系。

### 生态适配（2026：MCP / A2A / eval）

- **MCP**：**内部 plumbing 已具备**  
  - 缺口：对外文档、策略（allow/deny/auth）、以及工具调用的可观测/审计映射。
- **A2A 类 agent-to-agent 边界**：**缺失**
- **评测纪律（Eval）**：**缺失（first-class）**  
  - 有大量单元/验收测试，但缺少“质量回归”的行为评测与可比对回放。

---

## 2) 最关键短板（阻塞“实用 Agent”）

按“复利价值”排序：

1. **Eval + replay 作为产品能力**（golden traces + scoring）——让演进可被信任与快速迭代。  
2. **统一任务生命周期 UX 合约** —— 多通道不乱、不刷屏、状态可解释。  
3. **互操作边界** —— MCP（tools）+ A2A 风格（agents）对外扩展。  
4. **记忆质量 + 引用纪律** —— 提升能力同时保持可审计。  
5. **运维加固** —— profile、自检、证据工件输出。

