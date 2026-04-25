# 输出范例 — SecondBrain Markdown 与 Report Studio 导出

**英文 SSOT（信息等价、结构对齐）**：[`../en/output_examples_secondbrain_report.md`](../en/output_examples_secondbrain_report.md)。若与代码冲突，**以代码为准**。

**读者**：希望按可复制的 **golden path**，从内核行为得到 SecondBrain 树下的 **`.md` 落盘产物** 的运维人员。

---

## Block A — SecondBrain 上的 Markdown 落盘

### A.1 树所在位置

1. 根路径：**`settings.path_second_brain_root`**，可用 **`ADAMI_SECOND_BRAIN_ROOT`** 覆盖（未设置时常见为 `ADAMI_DATA_DIR/brain`）。详见 [knowledge_wiki_second_brain.md](knowledge_wiki_second_brain.md)。

### A.2 Intake 路径（文档 → Inbox）

1. **`DecisionProcessor`** 将 **`INTAKE` / `INTAKE_AUTO`** 路由到 **`_handle_intake_action`**（`src/adami_kernel/cortex/decision_processor.py`）。管线归档文档输出时，常以 Markdown + frontmatter 落在 PARA 下（多为 **`Inbox/`**）；`file_path`、`body_format: markdown` 等见文档管线专文 Step 4。

### A.3 Report Studio 持久化（`source="report_studio"`）

1. **`_handle_report_action`**（同文件）处理 **`/report …`** 子命令。执行 **`/report run <daily|weekly|monthly>`** 时调用 **`generate_fixed_blocks_report`**（`src/adami_kernel/peripheral/report_studio/report_generator.py`），再经 **`SecondBrainManager`** 落盘：
   - **`ReportConfig.write_to == "Resources"`** 时走 **`write_resource_note(...)`**；
   - **`write_to == "Inbox"`**（`ReportConfig` 默认）时走 **`write_inbox_note(...)`**。
2. 两函数定义于 **`src/adami_kernel/hippocampus/second_brain.py`**（底层 ingest：`second_brain_ingest.write_note`）。调用传入 **`source="report_studio"`** 与 **`dedupe_key`**，同日重复运行可合并为同一逻辑笔记。
3. 磁盘上可见类似 **`Inbox/report-YYYY-MM-DD-… .md`**（前缀来自 **`note_prefix`**，默认 `report`）。本地 `.adami_data/brain/Inbox/report-*.md` 即该模式。

### A.4 Report 配置文件

1. **`ReportConfigStore`**（`src/adami_kernel/peripheral/report_studio/report_store.py`）读写路径：

   `{brain_root}/System/working-memory/report_configs/{daily|weekly|monthly}.json`

2. **`ReportConfig`**（`report_config.py`）含 **`enabled`**、**`schedule`**（`timezone`、`publish_time_hhmm` 等）、**`sections`**（各块 `top_n`）、**`write_to`**（`"Inbox"` | `"Resources"`）、**`note_prefix`**。

---

## Block B — Report Studio（CLI / Telegram / Discord）

### B.1 前置条件

1. 运行中的 kernel（或任何能进入 **`DecisionProcessor._handle_report_action`** 的路径），且 kernel 对象已接线 **`second_brain`**。
2. 首次访问时 **`ReportConfigStore.ensure_defaults()`** 会补全缺失的 JSON 配置。
3. **可选更丰富正文**：**`toolbox.web`**（DuckDuckGo）改善新闻类块；**`kernel.router`** 提供报表生成中的 **`call_llm`** 翻译路径。若无网络或缺 Key，**各节可能为空**——仍会写入 Markdown；正文对空结果使用 **`report.studio.empty_*`** 等 i18n 占位，属**正常**而非写盘失败。

### B.2 命令（文本相同，载体不同）

1. **`/report help`**（或单独 **`/report`**）→ i18n **`dp.report.*`** 帮助正文。
2. **`/report list`** → 列出 `daily` / `weekly` / `monthly` 及路径。
3. **`/report show daily|weekly|monthly`** → 打印 JSON 配置（经 UI 适配）。
4. **`/report set daily|weekly|monthly <JSON>`** → 合并写入磁盘配置（须仍在 brain 根下）。
5. **`/report run daily|weekly|monthly`** → 内部生成 HTML/Markdown，**写入 SecondBrain**，再向会话推送**纯文本**摘录：
   - **Discord**：单块约 1800 字符上限；
   - **Telegram**：约 3800；
   - **CLI / 其他**：更大预算；见 **`report_port_format.py`** 中 **`plain_report_text_for_im_channels`**。

### B.3 Golden path（理想路径）

1. 确认对应类型 JSON 中 **`enabled: true`**（或通过 **`/report set …`** 打开）。
2. 发送：**`/report run daily`**（或 **`weekly`** / **`monthly`**）。
3. 预期：
   - 会话：**`dp.report.push_header`** 标题 + 分块正文（若节为空则可能很短）；
   - 磁盘：新建或更新 **`…/Inbox/report-… .md`**（若 `write_to` 为 **`Resources`** 则在 **`Resources/`**）；
   - 可选：日志或回复中含 **`dp.report.generated_path`** 与绝对 `path`。

### B.4 当各节看起来「空」时

1. **无网络 / 搜索被拦**：web 块可能为空；渲染 Markdown 仍有节标题，空位由 **`report.studio.empty_world_news`**、**`empty_ai`** 等填充——**仍算成功写盘**。
2. **`enabled: false`**：**`/report run`** 返回 **`dp.report.disabled`**，**不会**为该类型写新笔记。

---

## 延伸阅读

1. [profiles_shared_brain.md](profiles_shared_brain.md) — 共享脑与按工作流状态分工。  
2. [ARCHITECTURE.md](ARCHITECTURE.md) — Cortex / Nexus 拓扑。  
3. `docs/document_parsing_baseline_step0.md` — intake 与 Markdown 管线（Step 4）。

---

**Document baseline**: when this file changes materially, refresh SHA256 in `docs/internal/phase0_document_baseline.md` or record the new hash in your PR description.
