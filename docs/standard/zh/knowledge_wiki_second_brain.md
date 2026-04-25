# 知识 Wiki 叙事 — SecondBrain 与「无状态聊天」对照（AdamI）

**英文 SSOT（信息等价、结构对齐）**：[`../en/knowledge_wiki_second_brain.md`](../en/knowledge_wiki_second_brain.md)。若中英文叙述与代码冲突，以代码为准。

**读者**：希望在 Karpathy 式「可积累文库」隐喻下理解 AdamI，且要对齐本仓库真实代码路径的运维与集成方。

**代码真源（SSOT）**：`src/adami_kernel/hippocampus/second_brain.py`（`SecondBrainManager` 类 docstring 与模块级常量）。本文若与该文件不一致，**以该文件为准**。

---

## 1. 问题 — 无状态聊天与可积累文库

1. 无状态产品把单次会话当成用完即弃：输入、得到回答、关标签页，系统并不持有一份由你掌控的、结构化且持久的存储。
2. 典型 RAG 每次从上传或语料里重新捞片段；它本身不自动给出在明确规则下持续生长的**策展型、可互链知识库**。
3. 「LLM-Wiki」/ 馆员隐喻指的是：**知识在磁盘（或等价介质）上复利**，靠稳定路径、`summary` 与晋升规则积累，而不仅依赖易失的上下文窗口。

AdamI 以文件为载体的 **SecondBrain**（可配置根目录下的 PARA 形目录树）是这种「积累」在落盘侧的主叙事。它与基于 SQLite 的 **LayeredMemory**（工作流与系统持久化）**分离且互补**。

---

## 2. AdamI 栈 — 第二大脑落在哪里

1. **管理器**：`SecondBrainManager`（`src/adami_kernel/hippocampus/second_brain.py`）负责播种目录、写入身份种子文件、`Inbox`/`Resources` 等笔记写入，以及检索辅助函数。
2. **根路径**：由 `settings.path_second_brain_root` 解析；默认落在数据目录下的 `brain`，除非用环境变量 **`ADAMI_SECOND_BRAIN_ROOT`** 覆盖（见 `src/adami_kernel/config.py` 中的 `path_second_brain_root`）。
3. **教义**：给人看与 L1 注入的叙事文本在 `src/adami_kernel/SecondBrain.md`（同模块通过 `read_second_brain_doctrine` / `_SECOND_BRAIN_DOCTRINE_PATH` 只读加载）。树内操作性规则（例如 `System/working-memory/OPERATING_RULES.md`）在 kernel 接线后，会经 `PromptBuilder` 进入运行时身份相关注入。

---

## 3. 分层 — PARA 布局与代码实际扫描范围

1. **启动时保证存在的顶层目录**（来自 `SecondBrainManager.dirs`）：`Inbox`、`Projects`、`Areas`、`Resources`、`Archives`、`Identity`、`System/working-memory`，共同构成 manager 维护的 PARA 式工作区。
2. **`retrieve_brain_snippets(topic, max_files)`**（同文件）：**仅**扫描 **`Inbox/`**、**`Projects/`**、**`Resources/`** 三个目录——与常量 `_RETRIEVE_SNIPPET_SUBDIRS` 一致。每个目录只处理**直接子级**的 `*.md`，且**排除** `README.md`。匹配使用 YAML frontmatter 的 `summary`、正文首条 Markdown `#` 标题、路径 token 与话题字符串；**无向量嵌入**（方法 docstring 已写明）。
3. **`search_similar_skill`** 是另一条路径：在 **`Resources/`** 下递归扫描 `*.py` / `*.md`，overlap 打分，供 SkillFactory Tier3 兜底——**不要**与 `retrieve_brain_snippets` 的覆盖范围混为一谈。

因此：通过 `retrieve_brain_snippets` 得到的「wiki」是**浅层**的（三个文件夹各一层），不是整棵 PARA 树的语义检索。

---

## 4. 晋升 — 候选池、Identity 与教义

1. **`System/working-memory/candidates.md`**：晋升前观察到的偏好池；与 `SecondBrain.md` 中的协议一致（静默写入、用户触发 digest、确认后再晋升）。
2. **`Identity/`** 下如 `TELOS.md`、`CONTEXT.md`、`PROFILE.md`：由 manager 播种；教义要求 **Identity 级变更走人工审批**——不得在无人参与流程下自动改写 `TELOS.md`。
3. **Intake 与移动**：`move_brain_note()` 与 ingest 辅助逻辑保证路径不越出 brain 根；追踪多模态或报表写入 `Inbox` / `Resources` 时，应沿这些 API 与路径理解。

本节是与 `SecondBrain.md` 的叙事对齐；实际约束分散在提示词、hook 与人的流程中，**不是**单条 SQL 能概括的。

---

## 5. 尚非完整 Wiki — LayeredMemory 与诚实边界

1. **`LayeredMemory`**（`src/adami_kernel/hippocampus/layered_memory.py`）把**工作流状态**、经验、checkpoint 及相关 domain 落在 **`settings.path_l2_memory_db`**（默认常见为 `.adami_data` 下 SQLite）。这是**编排与 episodic** 持久平面，不是 Markdown 树。
2. SecondBrain 的 Markdown 与 `LayeredMemory` 分工不同：**文件**承载人类可读、可 diff 的知识与报表；**数据库**承载工作流图与高体量轨迹。
3. AdamI **目前不承诺**：全库笔记自动双向 wikilink、单次调用覆盖整棵 PARA 的全图 RAG、或与 Obsidian 的原生双向同步——这些都是在上述分工之上的产品扩展。
4. `LayeredMemory` 内的 Chroma / 向量路径为可选且受依赖开关约束；除非你的部署显式启用并调参，否则应把向量召回视为与 `retrieve_brain_snippets` **正交**的能力。

---

## 6. 延伸阅读

1. 技术拓扑：`docs/standard/zh/ARCHITECTURE.md`（Hippocampus 与事件流）。
2. 英文版叙事（便于 PR 与外部引用）：`docs/standard/en/knowledge_wiki_second_brain.md`。

---

**Document baseline**: when this file changes materially, refresh SHA256 in `docs/internal/phase0_document_baseline.md` or record the new hash in your PR next to Phase 0 fingerprints.
