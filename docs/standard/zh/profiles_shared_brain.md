# Profile、角色与共享 SecondBrain（对照 Hermes 的映射说明）

**英文 SSOT（信息等价、结构对齐）**：[`../en/profiles_shared_brain.md`](../en/profiles_shared_brain.md)。若叙述与代码冲突，**以代码为准**。

**读者**：希望在 Hermes 式「多代理 + profile + 共享知识库」话术下，理解 AdamI 的 **工作流 + MAO + SecondBrain** 栈的运维与开发。

**代码真源（SSOT）**：`src/adami_kernel/orchestrator/workflow_models.py`（`WorkflowState`）、`src/adami_kernel/orchestrator/multi_agent_orchestrator.py`（`MultiAgentOrchestrator`）、`src/adami_kernel/hippocampus/second_brain.py`（`SecondBrainManager`）、`src/adami_kernel/config.py`（`path_second_brain_root`）。

---

## 1. 为何需要这份映射

Hermes 用 **profile**（子代理各自记忆、会话、技能）加上 **共享知识层**，避免子代理「从零冷启动」。AdamI 的原语不同——**持久化 DAG 状态**、**`WorkflowState.context`**、**`MultiAgentOrchestrator`** 按角色分发——但产品问题一致：**谁隔离、谁共享、长期知识落在哪？**

---

## 2. 概念映射（Hermes → AdamI）

1. **Hermes「profile」（子代理独立配置）** → **`WorkflowState.metadata`**（自由 `Dict[str, Any]`）。用字符串 **`profile_id`** 标记稳定、可 grep 的编排来源。内核入口会调用 **`workflow_models.ensure_default_profile_id`**，新建工作流即带默认值（见 **§3 Contract**）。其他键（如 `long_task_tracking_enabled`）已在真实载荷中出现——可将 `metadata` 视为 profile 类标签的扩展点。

2. **Hermes「子代理实例」** → **`MultiAgentOrchestrator`**（`src/adami_kernel/orchestrator/multi_agent_orchestrator.py`）内按 **`AgentRole`** 划分的 worker，以及各自的 **`WorkflowState.context`** 项（`engineer`、`researcher`、`_skill_name` 等）。编排器按角色构造 **`AgentMessage`**，经 **`agent.communication`** 发布。

3. **Hermes「子会话 / 嵌套 worker」** → **`WorkflowState.parent_workflow_id`**（`workflow_models.py`）：在组合或分叉图时把子实例连到父级 **`workflow_id`**。用于血缘与排障，**不是**第二个文件系统根。

4. **Hermes「共享 LLM-Wiki / 知识库」** → 当前为 **单一物理 SecondBrain 树**：根由 **`settings.path_second_brain_root`** 解析，可用 **`ADAMI_SECOND_BRAIN_ROOT`** 覆盖。共享的人类可读锚点包括 **`Identity/TELOS.md`**、**`Identity/CONTEXT.md`**、**`Identity/PROFILE.md`**、**`System/working-memory/OPERATING_RULES.md`**——由 **`SecondBrainManager`** 播种与读取。片段检索范围见 [knowledge_wiki_second_brain.md](knowledge_wiki_second_brain.md)（`retrieve_brain_snippets`）。

5. **Hermes「子代理看到 Wiki 语境」** → 在 AdamI 中，**同一 kernel 实例内**各角色在组件图把同一个 manager 接入 **`PromptBuilder`**、intake、报表等路径时，读的是 **同一** `SecondBrainManager`。**按角色隔离** 主要在 **`WorkflowState.context`** 与 MAO 消息载荷中，而非多套 brain 目录——除非你部署多个 kernel 并配置不同的 **`ADAMI_SECOND_BRAIN_ROOT`**。

---

## 3. Contract（`WorkflowState.metadata`）

1. **`profile_id`**（字符串，推荐）：标明工作流由哪类工厂创建，便于日志与过滤；**仅为编排元数据**——Report Studio 与 SecondBrain ingest 路径不读取该键。

2. **`ensure_default_profile_id(state, profile_id)`**（`workflow_models.py`）等价于 **`state.metadata.setdefault("profile_id", profile_id)`**，调用方若已写入自定义值则 **不会** 被覆盖。

3. **默认写入方（已实现）**：
   - **`create_initial_workflow_state`** → `profile_id="planner_initial"`（Planner 快速初始状态）。
   - **`MultiAgentOrchestrator.start_multi_agent_workflow`** → `profile_id="multi_agent_orchestrator"`。
   - **`SkillComposer`** 组合或 fallback 返回的 **`WorkflowState`** → `profile_id="skill_composer"`。

4. **计划内 / 手工**：测试或特性代码中手写 **`WorkflowState(...)`** 仍可暂不写 **`profile_id`**，直至各调用点补齐——字段可选，故安全。

---

## 4. 多角色运行时（日志在说什么）

1. **`MultiAgentOrchestrator`** 维护 **`active_orchestrations: Dict[str, WorkflowState]`**（按 workflow id），并向已注册代理派发 **`AgentTask`**（如 `ExecutorAgent`、Researcher、Engineer）。

2. 下游需要上游产物时，编排器把 **`state.context`** 的切片写入 **`AgentMessage.payload`**（例如 Engineer 收到 **`original_task`** 片段；Executor 收到 **`skill_name`** / **`args`**）。

3. 调试日志使用 i18n 键如 **`orch.magent.debug.role_ctx`**（为 `{role}` 注入 context、`{keys}`）——在运维语义上最接近 Hermes 文案里的「按 profile 注入上下文」。

---

## 5. 单物理根与后续多根

1. **当前默认**：每个运行中的 kernel 配置对应 **一个** SecondBrain 目录树，适合多数单租户与开发环境。

2. **强隔离**（每客户独立 vault、每 profile 独立 `brain/` 树）**不在**本文档范围内作为一等开关：涉及多数据根、迁移与访问控制——若产品需要，单列后续 Phase。

3. 在此之前，**逻辑**隔离应通过 **`metadata.profile_id`**、**`chat_id`**、**`WorkflowState.context`** 边界表达；**共享**的长文知识仍落在单一 **`path_second_brain_root`** 下。

---

## 6. 与 Planner 的关系（无矛盾）

1. **`Planner`**（`src/adami_kernel/orchestrator/planner.py`）可走 **`WorkflowEngine`** 组合路径，或在技能创建等流程回退到 **`MultiAgentOrchestrator`**。使用引擎时，两条路径最终都会经 **`LayeredMemory`** 持久化 **`WorkflowState`**。

2. 本文档 **不修改** Planner 契约；只标明 **profile 类** 与 **共享脑** 概念应挂载何处，避免维护者再发明重复的「第二知识根」。

---

## 7. 延伸阅读

1. [knowledge_wiki_second_brain.md](knowledge_wiki_second_brain.md) — 落盘 Wiki 叙事与 `retrieve_brain_snippets` 边界。  
2. [ARCHITECTURE.md](ARCHITECTURE.md) — 含 Hippocampus 与 MAO 的拓扑。  
3. `src/adami_kernel/hippocampus/README.md` — 记忆模块边界。

---

**Document baseline**: when this file changes materially, refresh SHA256 in `docs/internal/phase0_document_baseline.md` or record the new hash in your PR description.
