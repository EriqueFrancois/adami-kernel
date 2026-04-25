# AdamI：NLU 增强选项备忘 + 路由误判案例

本文档供内部备用：第一部分为「外部 NLU/结构化库是否适合集成」的结论摘要；第二部分为「日本 5 日游 → 地震数据」类误判的工程原因分析。

---

## 第一部分：库级集成结论（摘要）

| 方案 | 与 AdamI 契合度 | 可行性 | 对「理解错意图」的作用 |
|------|-----------------|--------|-------------------------|
| **DeepPavlov** | 闭集意图+槽位；与开放 Agent 双轨 | 中偏低（重依赖、运维） | 仅固定意图族，难覆盖开放任务 |
| **Instructor** | 与现有 Pydantic 一致；接 Planner/SkillRouter 结构化输出 | **高**（注意多 LLM 后端对 JSON mode 的支持） | 主要减少 **格式/解析** 错误，不单独保证语义选对 |
| **Rasa** | 完整 NLU+对话；与动态技能宇宙并行 | 中（独立服务+标注迭代） | 闭集强；开放域仍依赖 LLM |
| **Outlines** | 约束解码；适合本地路由小模型 | 中（推理栈） | 合法输出 ≠ 正确意图 |
| **JointBERT** | 与 Hybrid 快脑、闭集分流一致 | 中（数据与训练） | 分布内降误分，分布外回退 LLM |
| **TEXTOIR** | 开放意图发现；偏研究管线 | 偏低 | 偏离线发现，非单次在线主路由 |
| **HanLP** | 中文分词/NER 预处理 | **高** | 间接减少分词/实体边界导致的下游误判 |

**落地优先级建议**：Instructor/结构化输出 →（可选）HanLP 中文预处理 →（可选）JointBERT 闭集分流；Rasa/DeepPavlov 除非明确要双轨闭集对话，否则成本偏高。

---

## 第二部分：指令「帮我做一个日本5日游的旅行规划」却执行地震查询

### 现象对齐

返回结构为 `地点 / 震级 / 时间 / 深度(km)` 的中文字段列表，与仓库内 **本能技能** `.adami_data/instincts/EARTHQUAKE_QUERY.py`（USGS `all_day.geojson`）的输出形态一致，可认定实际执行的是 **地震查询类技能**（`EARTHQUAKE_QUERY` 或等价注册名），而非旅行规划类 Anthropic 工作流或通用 Planner 文本回答。

### 可能原因（按链路从强到弱）

#### 1. SkillRouter 的 LLM 路由「语义错配」（最常见）

`SkillRouter._decide_and_extract` 使用 `sr.llm.route_header` 提示，让模型在 **候选技能列表** 中选 `matched/skill_name/args`。模型容易把 **「日本」** 与 **地缘/灾害/地震带** 训练先验关联，在候选里若存在 **地震/USGS/地理** 相关技能或描述中含 *Japan* 的元数据，会 **错误地 `matched: true`** 并返回该技能名。

- 这与「指令字面是旅行规划」并不矛盾：**当前提示未强制区分「信息检索类工具」与「开放式行程规划」**，也没有「无合适工具则 matched=false」的硬约束校验层。

#### 2. 向量检索把地震技能推进候选集

若运行环境中 **Anthropic 技能目录未加载或缓存为空**，或 `top_k` / 候选合并策略与主线版本不一致，`vector_store.search("…日本…")` 可能因技能说明、历史 WF 代码注释、示例里出现 **Japan / Honshu / 海啸** 等文本，与查询 embedding 相近，从而把 **EARTHQUAKE_QUERY** 推入候选，再被 LLM 选中。

#### 3. `SkillRouter._get_candidates` 的截断策略（需对照你部署的 commit）

在 **当前主线实现** 中：`candidates` 先 `extend` 整表 Anthropic 技能，再拼向量结果，最后 **`return candidates[:top_k]`（默认 `top_k=5`）**。若 Anthropic 列表长度 ≥5，则 **仅前 5 条 Anthropic 进入 LLM 视野**，其后向量/关键词结果可能被截掉——此情况下 **本能地震技能不应出现在候选里**。若你仍能稳定复现地震被选中，说明实际运行可能是：

- 旧版本/分支中 `top_k` 或拼接顺序不同；或  
- 本机 **Anthropic 扫描为空**，候选主要来自向量/关键词；或  
- 地震并非经 SkillRouter，而经 **Planner 其它分支 / 多 Agent 工具调用**（需对照当次 `trace_id` 日志中的 `plnr.log.sr_ok` / `skrt.log.match_ok`）。

#### 4. Planner 的「技能名子串命中」分支（通常不应命中 `EARTHQUAKE_QUERY`）

`planner.py` 中存在 `skill_name.lower() in task.lower()` 与 `s in task` 的兜底：仅当 **技能注册名整段出现在用户原文** 时才会命中。`earthquake_query` 一般不会出现在中文旅行句中，**该路径概率低**，除非存在极短或中文别名的异常注册名。

### 结论（给排障与后续改动的方向）

- **根因类型**：以 **LLM 技能路由 + 缺少任务类型门禁** 为主（语义错配）；环境与候选截断会改变「地震技能是否进候选」。
- **为何与「日本」强相关**：地名触发 **灾害/地理** 联想 + 技能元数据/向量侧 **Japan 共现**，放大了错选概率。
- **改进方向（与第一部分一致）**：  
  - 对「开放规划类」任务：**先** Intent/Hybrid 判为 **非工具短答** 或 **matched=false**，再走多 Agent / 纯 LLM；  
  - 对工具调用：**Pydantic/JSON Schema + Instructor 或等价** 强制 `task_type` / `tool_choice`；  
  - 候选层：**旅行类关键词抑制** `EARTHQUAKE_*` 或要求地震类必须显式出现「地震/震级/USGS」等触发词；  
  - 观测：每次路由落库 **候选列表 + LLM 原始 JSON**，便于复现。

---

*文档生成：与对话中分析一致，随实现变更请同步更新候选截断与路由相关代码引用。*
