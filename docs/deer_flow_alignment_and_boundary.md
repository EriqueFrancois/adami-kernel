# DeerFlow 范式对齐与集成边界 — 模块四步骤 0 定稿

本文档固定 **AdamI × [bytedance/deer-flow](https://github.com/bytedance/deer-flow)** 的**范式对齐目标**与**工程边界**，供后续步骤（阶段产物、统一 checkpoint、失败恢复、可选侧车等）验收对照。**步骤 0 不包含**可执行集成代码；代码从后续步骤按路线图增量落地。

---

## 1. DeerFlow 是什么（避免期望偏差）

**官方定位（只读调研结论）**

- 仓库：<https://github.com/bytedance/deer-flow>
- DeerFlow（Deep Exploration and Efficient Research Flow）2.0 定位为开源 **长时程 SuperAgent 底座**：子 Agent、记忆、沙箱、工具与 **Skills**、消息网关等协同，面向「数分钟到数小时」量级的任务；技术栈为独立 **Python 后端**（如 `config.yaml` 驱动模型）与 **Node 前端**，可选 Docker 部署、MCP、LangSmith/Langfuse 等观测。

**明确不是**

- DeerFlow **不是** AdamI 内核的「替代品」或「默认内嵌运行时」。将其整仓作为 monorepo 子树并随 **默认 wheel** 一并发布，会导致双套编排、双套记忆模型与运维面不可控膨胀。
- 集成目标是对标其 **任务生命周期工程化**（研究 → 写代码 → 跑测 → 迭代 → 交付），在 AdamI 的 **单一工作流真源** 上补齐 checkpoint、阶段产物、恢复语义；而非在仓库内维护第二套 Agent 主循环。

---

## 2. 单一真源与「双运行时」禁令（评审必过条款）

**工作流真源（Single Source of Truth）**

- 任意长任务在 AdamI 侧必须以 **`workflow_id`（及租户维度的 `chat_id`）** 为主键，持久化于 **`LayeredMemory` + `WorkflowState`**（见 `src/adami_kernel/orchestrator/workflow_models.py`、`workflow_engine.py`）。
- 事件推进仍以 **`EventBus` 上的 `workflow.events`（及现有编排契约）** 为准；后续步骤若引入「阶段」「checkpoint 指针」，必须能关联回上述同一 `workflow_id`，不得在平行命名空间另起一套「任务 ID」而不做映射。

**双运行时禁止默认并存**

- **默认构建与默认运行路径**不得同时挂载两套「主编排运行时」（即：AdamI `WorkflowEngine` / `MultiAgentOrchestrator` **与** DeerFlow 进程内 Python 包级深度耦合作为主循环）。
- 若选用 **档位 B**（外部 DeerFlow），DeerFlow 仅允许作为 **可选执行后端 / 侧车**：由 AdamI 在**显式开关**下委托子步骤，且未启用开关时行为与当前内核 **完全一致**（无静默依赖 DeerFlow 进程或网络）。

**评审自检句**

- 「谁拥有 `workflow_id`？」→ **仅 AdamI 内核与 `LayeredMemory`。**
- 「默认 `poetry install` 是否拖入 DeerFlow 全栈？」→ **否**（除非将来以 **optional extra** 明确声明，且仍不成为默认主循环）。

---

## 3. 责任边界：checkpoint、沙箱、产物（无歧义）

**Checkpoint（断点 / 阶段恢复数据）**

- **写、读、版本语义的主责任方：AdamI**，通过 `LayeredMemory` 及后续步骤约定的统一命名空间（例如按 `workflow_id` + 阶段键）；各 Agent（如 `Researcher`）若已有域内 checkpoint，应逐步 **收敛到同一契约**，避免仅部分角色可恢复。
- **DeerFlow（档位 B）** 若内部也有记忆或检查点：视为 **从属副本**；同步回 AdamI 时须写入与 `workflow_id` 绑定的结构，**不得以 DeerFlow 内部 ID 作为运维与恢复的唯一依据**。

**沙箱与外部执行（代码运行、测试命令等）**

- **执行责任方**：沙箱进程 / 容器 / 外部 Runner（可为 AdamI 自有封装，或 DeerFlow 提供的沙箱环境）。
- **编排与审计责任方**：AdamI；须在 `WorkflowState` / 阶段产物中记录 **可引用句柄**（日志路径、artifact URI、`run_id`、退出码等），内核进程不替代沙箱承担任意代码执行的安全边界。

**阶段产物（结构化交付物）**

- **schema 与落盘策略的主责任方：AdamI**（后续步骤定义 `StageArtifact` 或等价结构）；DeerFlow 仅作为可选 **生产者** 之一，通过适配层把输出映射进 AdamI 契约。

---

## 4. 三种集成档位（A / B / C）

### 档位 A — 仅内核范式补齐（默认路线）

- **内容**：在 AdamI 内完成阶段模型、统一 checkpoint、失败恢复与阶段产物结构化；不依赖 DeerFlow 部署。
- **操作倾向**：修改/扩展 `orchestrator`、`LayeredMemory` 契约、测试与文档；**不**新增 DeerFlow 为安装依赖。
- **目的**：用 DeerFlow 的**产品范式**补 AdamI 长任务工程化短板，供应链最简。

### 档位 B — 内核 + 外部 DeerFlow（HTTP / CLI 适配器，可选）

- **内容**：在 **显式配置开关** 下，将某一类节点或子任务 **委托** 给已部署的 DeerFlow 实例（HTTP 或 CLI）；AdamI 负责发起、轮询/回调、**把结果写回** `WorkflowState` / 阶段产物。
- **操作倾向**：新建适配模块（例如 `integration/deer_flow/`）、环境变量与文档；依赖放入 **optional extra** 或仅标准库/httpx 级薄客户端，**禁止**默认安装 DeerFlow 全仓库。（实现锚点：`integration/deer_flow_bridge.py`；安全：`docs/deer_flow_bridge_security.md`。）
- **目的**：复用 DeerFlow 工具链与沙箱能力，同时保持 AdamI 为唯一主控与持久化真源。

### 档位 C — 子模块 / git subtree 只读对照

- **内容**：将 `deer-flow` 以 submodule 或 subtree 置于仓库外路径或 `vendor/` **仅作文档与实现参考**，**不**参与默认 `pip install` / wheel 构建；不将 DeerFlow 源码编译进默认发行物。
- **操作倾向**：可选新建 `.gitmodules` 或贡献指南中的「对照克隆」说明；CI 默认 **不**构建 DeerFlow 前端/后端。
- **目的**：降低「口头对齐、实现漂移」风险，工程师可本地对照 API 与模式，而不污染内核包边界。

**档位选择约定**

- **默认启用档位 A**；档位 B、C 须在配置与文档中 **显式打开**，且满足上文「双运行时禁止默认并存」。

---

## 5. AdamI 当前相关实现锚点（只读）

- 工作流状态与持久化：`src/adami_kernel/orchestrator/workflow_models.py`（`WorkflowState`）、`workflow_engine.py`（含 `PAUSED` / `resume_workflow`）
- 记忆层：`LayeredMemory`（`save_workflow_state`、`get_workflow_state`；及现有 `get_workflow_checkpoint` 等扩展点）
- 多 Agent：`src/adami_kernel/orchestrator/multi_agent_orchestrator.py`
- 研究侧 checkpoint 示例：`src/adami_kernel/orchestrator/agents/researcher.py`

后续步骤（阶段 schema、统一 checkpoint API、阶段闸事件等）应在此文档边界内增量实现，并在 PR 描述中引用本文 **§2–§4** 条款做自检。

---

## 6. 步骤 0 关键检测（本仓库可执行）

- **文档评审**：任意读者能回答 ——「工作流真源在哪？」「默认会不会跑两套主循环？」「checkpoint 谁写、沙箱谁跑？」—— 且与本文 **§2、§3** 一致。
- **构建检测**：默认 `poetry install` / 打包流程 **不**因 DeerFlow 引入新硬依赖而失败（步骤 0 不添加依赖；若 README 已引用本文，可选运行 `poetry check` 确认无变更需求）。

**步骤 0 完成标志**：`docs/deer_flow_alignment_and_boundary.md` 存在且与 `tasklist.md`、仓库级 README 的模块四引用一致；团队对「集成是什么」有统一口径。
