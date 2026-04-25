# Document parsing pipeline — Step 0 baseline (no behavior change)

This document records the document-parsing integration plan and baseline. **Step 0** snapshots pre-change behavior; **Steps 1–8** cover optional MarkItDown, the `document_markdown` bridge, `MultiModalInput` wiring, intake, skills SSOT, ops toggles / logging, bridge test matrix + CI job, and release/migration notes (no root `CHANGELOG`).

---

## English

### Entry points and `media_type`

- **Telegram / Discord attachments** (and similar ports) save files to a temp path and publish events whose payload includes `file_path` and typically `file_name`. When classified as a **document**, downstream code uses **`media_type == "document"`** (not `"file"` — the return payload from `MultiModalInput._process_file` uses `media_type: "file"` in the `raw_multi_modal` dict; the **router** uses `"document"` when calling `process_input`).

- **Voice** is forced by extension (`.ogg`, `.mp3`, …) to `_process_voice` even if labeled oddly.

- **Photo** → `_process_image` (BLIP caption path).

### `MultiModalInput._process_file` (`src/adami_kernel/cortex/multi_modal.py`) — **Step 3**

1. If **`file_path` missing or not on disk**:
   - Returns **`type: "raw_multi_modal"`**, `raw_content` from **`mmodal.file.bad_path`**, `media_type: "file"`.
2. If the basename suffix is **`.pdf` / `.docx` / `.pptx` / `.xlsx`** (case-insensitive): if **`markitdown_effective_enabled()`** (Step 6: `ADAMI_MARKITDOWN_ENABLED` auto/force/off), call **`document_markdown.convert_document_path_to_markdown`** (MarkItDown, `enable_plugins=False`, timeout from **`ADAMI_DOCUMENT_MARKDOWN_TIMEOUT_SEC`**, default **45s**, same budget as **`partition`**). If MarkItDown is skipped by config or auto-without-package, log and fall through like **`not_installed`**.
   - **Success**: returns **`type: "raw_multi_modal"`**, **`raw_content`** = Markdown string, **`media_type: "file"`**, **`task`** = **`mmodal.file.task_analyze`** (same payload shape as the unstructured success path so `DecisionProcessor` is unchanged).
   - **Failure** (including **`not_installed`** when the Poetry extra is absent): log **INFO** for missing MarkItDown, **WARNING** once for other reasons, then fall through to **`partition`** when `unstructured` is available.
3. If **`unstructured` is not importable** at construction time (`unstructured_available == False`) and step 2 did not already return Markdown:
   - Returns **`type: "text"`**, `content` from **`mmodal.file.missing_unstructured`** (mentions optional **`poetry install -E markitdown`** for the four suffixes and **`unstructured[all-docs]`** with `{exe}`).
4. Otherwise runs **`unstructured.partition.auto.partition(filename=file_path)`** in **`asyncio.to_thread`**, timeout **`ADAMI_DOCUMENT_MARKDOWN_TIMEOUT_SEC`** (default **45s**); success/timeout/error paths unchanged (`mmodal.file.task_analyze`, `mmodal.file.timeout_body`, `mmodal.file.extract_failed`).

`unstructured` remains **optional** at runtime (not in default `pyproject.toml` dependencies); MarkItDown is optional via **`poetry install -E markitdown`**.

### `DecisionProcessor` — document → LLM

- **`_detect_multimodal_intent`**: if payload has **`file_path`** or the string **`"document"`** appears in `task` (case-insensitive), returns **`("PARSE_DOCUMENT", {"file_path": ...})`**.
- **`_dispatch_multimodal_task`** calls **`_execute_action("PARSE_DOCUMENT", ...)`** → **`multi_modal.process_input("document", {"file_path": ...})`** (no `file_name` passed here; optional improvement later).
- If the result is a dict with **`type == "raw_multi_modal"`**:
  - Builds prompt **`dp.multimodal.doc_analyst_prompt`** with **`raw_content[:4000]`** and locale style keys **`dp.multimodal.locale_style_*`**.
  - Calls **`router.call_llm(..., brain_type="action", temperature=0.3)`**.
  - Stores experience and sends the **LLM summary string** as the user-visible reply.

So: **Markdown (when MarkItDown succeeds) or unstructured plain text → truncated raw → single LLM summarization** is the document understanding contract toward the LLM.

### Intake (`/intake`, `INTAKE`, `INTAKE_AUTO`) — **Step 4**

- **`DecisionProcessor.process`**: **`INTAKE` / `INTAKE_AUTO`** are routed **before** `PARSE_DOCUMENT` when the intent matches, so a single event can carry **`file_path`** and still archive via intake.
- **`_handle_intake_action(task, …, payload)`**: if **`payload["file_path"]`** points to an existing file, calls **`toolbox.multi_modal.process_input("document", {file_path, file_name})`** (same MarkItDown → unstructured stack as Step 3). On **`raw_multi_modal`**, the note body is **`raw_content`** (Markdown when MarkItDown wins). Otherwise the body stays **`task`**. Optional YAML when a file was ingested: **`source_file`**, **`body_format: markdown`**. **`call_llm`** is still used **only** for frontmatter metadata (domain, tags, PARA).
- **4.2 (optional / later)**: summarize only when Markdown exceeds a threshold before write — not implemented in Step 4 (full body / current excerpt window for metadata only).

### Skills vs kernel

- **`skills/skills/pptx/SKILL.md`** and **`editing.md`** still describe **`python -m markitdown`** and **`pip install "markitdown[pptx]"`** for **offline / skill-sandbox** workflows. After kernel integration, these become **supplementary**; the canonical path will be **in-process API** (documented in README and this doc’s future revision).

---

## 中文（步骤 0 基线，无行为变更）

### 入口与 `media_type`

- **Telegram / Discord** 等端口将附件落盘后在事件 payload 中带 **`file_path`**、**`file_name`**。归类为**文档**时，下游对 `MultiModalInput` 使用 **`process_input(..., "document", {...})`**。
- **语音**按扩展名（`.ogg`、`.mp3` 等）强制走 **`_process_voice`**。
- **图片**走 **`_process_image`**（BLIP）。

### `MultiModalInput._process_file`（`multi_modal.py`）— **步骤 3**

1. **`file_path` 无效**：**`mmodal.file.bad_path`**，`media_type: "file"`。
2. 后缀为 **`.pdf` / `.docx` / `.pptx` / `.xlsx`**（大小写不敏感）：先走 **`document_markdown.convert_document_path_to_markdown`**；成功则 **`raw_multi_modal`** + Markdown **`raw_content`** + **`mmodal.file.task_analyze`**；失败（含未安装 MarkItDown）打 **INFO/WARN** 后若已安装 **`unstructured`** 则回退 **`partition`**（45s 超时不变）。
3. **未安装 `unstructured`** 且上一步未产出 Markdown：返回 **`type: "text"`**，**`mmodal.file.missing_unstructured`**（同时提示可选 **`poetry install -E markitdown`** 与 **`unstructured[all-docs]`**）。
4. **`partition`** 成功 / 超时 / 异常：与原先 **`mmodal.file.*`** 行为一致。

**`unstructured`** 仍多为环境自行安装；**MarkItDown** 为 Poetry 可选 extra。

### `DecisionProcessor` — 文档 → LLM

- **`_detect_multimodal_intent`**：有 **`file_path`** 或 `task` 中含 **`document`**（忽略大小写）→ **`PARSE_DOCUMENT`**。
- **`_dispatch_multimodal_task`** → **`process_input("document", ...)`**。
- 若 **`type == "raw_multi_modal"`**：用 **`dp.multimodal.doc_analyst_prompt`** 与 **`raw_content[:4000]`** 调 **`router.call_llm`**，用户看到的是 **摘要回复**。

### Intake — **步骤 4**

- **`process`**：命中 **INTAKE / INTAKE_AUTO** 时**先于** `PARSE_DOCUMENT` 处理，以便同一条事件带 **`file_path`** 仍走归档。
- **`_handle_intake_action`**：若 **`payload`** 含有效 **`file_path`**，经 **`multi_modal.process_input("document", …)`** 与多模态同源；成功则正文为 **`raw_content`**（Markdown 优先）；否则正文仍为 **`task`**。YAML 可写 **`source_file`**、**`body_format: markdown`**。**`call_llm`** 仍只负责元数据。

### Skills 与内核

- PPTX 技能文档中的 **MarkItDown CLI** 在集成完成前仍有效；集成后以**内核内 API**为准，CLI 仅作调试补充。

---

## Step 1 (dependencies)

- **Poetry**: optional dependency `markitdown` with `extras = ["pdf", "docx", "pptx", "xlsx"]`, version `~0.1.5`, `optional = true`.
- **Extra group name**: `markitdown` → install with `poetry install -E markitdown`.
- **Default**: `poetry install` leaves MarkItDown out; `import markitdown` fails until the extra is installed.
- **Rationale**: smaller default attack surface and install size; aligns with upstream optional format deps.

---

## Step 2 (document → Markdown bridge)

- **Module**: `src/adami_kernel/cortex/document_markdown.py` (canonical kernel API; callers should not import `MarkItDown` directly).
- **Entry points**: `convert_document_path_to_markdown`, `convert_document_stream_to_markdown` — async wrappers that run blocking `MarkItDown().convert(...)` in `asyncio.to_thread` under `asyncio.wait_for` (configurable timeout; default matches `MultiModalInput` partition timeout).
- **MarkItDown**: `MarkItDown(enable_plugins=False)` to reduce untrusted plugin risk.
- **Whitelist**: suffixes `.pdf`, `.docx`, `.pptx`, `.xlsx` only (case-normalized via `Path.suffix.lower()`).
- **Success payload**: Markdown `str` plus metadata: `truncated`, `original_char_length`, optional `title`. Default char cap **4000** (same window as `DecisionProcessor` / `tools_manager` document excerpts).
- **Failure payload**: `DocumentMarkdownFailure` with `DocumentMarkdownFailureReason` (`not_installed`, `disallowed_extension`, `path_missing`, `file_too_large`, `timeout`, `unsupported_format`, `conversion_failed`, etc.) so **`MultiModalInput` (Step 3)** can fall back to `unstructured`.

### 中文（步骤 2：文档 → Markdown 桥）

- **模块**：`cortex/document_markdown.py` 为内核权威 API；业务代码不要直接依赖 `MarkItDown` 类。
- **异步**：对外仅 async；内部 `to_thread` + 超时，避免阻塞事件循环。
- **白名单**：仅 pdf / docx / pptx / xlsx；失败返回结构化原因，供 **`multi_modal`（步骤 3）** 回退 `unstructured`。

---

## Step 3 (`MultiModalInput` document path)

- **Order**: `bad_path` check → **MarkItDown** (via `document_markdown`) for whitelisted suffixes → on failure or skip, **`unstructured.partition`** when importable → existing timeout/error user strings.
- **Logging**: `not_installed` → **INFO** (`mmmd.log.markitdown_unavailable`); other MarkItDown failures → **WARNING** (`mmmd.warn.markitdown_fallback`); unstructured errors remain **ERROR** as before (no duplicate MarkItDown ERROR spam).
- **i18n**: `mmodal.file.missing_unstructured` updated to mention both optional MarkItDown and unstructured; `doc.pipeline.step3` summarizes the pipeline for UI.

### 中文（步骤 3：`multi_modal` 文档主路径）

- **顺序**：无效路径 → 白名单四类先 **MarkItDown** → 失败或未装则 **unstructured** → 仍无解析器则 **`mmodal.file.missing_unstructured`**。
- **日志**：未装 MarkItDown 用 **INFO**；其它 MarkItDown 失败 **WARN** 一次；`partition` 异常/超时仍为 **ERROR**。
- **文案**：`mmodal.file.missing_unstructured` 合并简短可选依赖说明；`doc.pipeline.step3` 为 UI 一行提示。

---

## Step 4 (intake / SecondBrain archive)

- **`decision_processor.py`**: `_handle_intake_action` reuses **`MultiModalInput`** for on-disk **`file_path`**; Inbox **`.md`** body prefers converter output; metadata LLM still sees **`archive_body[:4000]`** (same cap as before on the prompt input).
- **i18n / logs**: `dcpu.log.intake_markdown`, `dcpu.warn.intake_doc_extract`, `doc.pipeline.step4`.

### 中文（步骤 4：intake 归档）

- 与多模态**同一** `process_input("document")` 路径；无解析器时行为与仅 **`task`** 写入一致。

---

## Step 5 (skills documentation / SSOT)

- **Goal**: Skill markdown under `skills/` should not tell users to `pip install markitdown` or run `python -m markitdown` for normal flows. Document→Markdown is owned by the **kernel** (`adami_kernel.cortex.document_markdown`, async `convert_document_path_to_markdown` / `convert_document_stream_to_markdown`; same stack as `MultiModalInput` and intake).
- **Skills**: Example alignment in `skills/skills/pptx/SKILL.md` and `skills/skills/pptx/editing.md`. Optional **MarkItDown CLI** may appear only in an explicit **Dev-only / offline debugging** section, labeled **not production**.
- **i18n / UI**: `doc.pipeline.step5` in `locales/*/common.json`.

### 中文（步骤 5：技能文档与内核一致）

- **目标**：`skills/` 下说明不以 **pip 安装 markitdown** 或 **`python -m markitdown`** 作为生产路径；文档→Markdown 以 **`document_markdown`** 模块为单一事实来源。
- **可选 CLI**：仅允许放在标为 **开发调试、非生产** 的小节中。

---

## Step 6 (config / observability / rollback)

- **`Settings` (`config.py`)** — non-secrets; prefer class defaults over `.env` unless you need an environment override:
  - **`ADAMI_MARKITDOWN_ENABLED`**: `True` (default) = **force** the MarkItDown path first for whitelisted suffixes (still returns `NOT_INSTALLED` if the extra is absent). `None` = **auto** — run the MarkItDown attempt only when `importlib.util.find_spec("markitdown")` succeeds. `False` = **kill-switch** (skip MarkItDown; `multi_modal` goes straight to unstructured / missing extractors).
  - **`ADAMI_DOCUMENT_MARKDOWN_TIMEOUT_SEC`**: shared timeout for MarkItDown convert and unstructured `partition` on the same on-disk path (default `45.0`).
  - **`ADAMI_DOCUMENT_MARKDOWN_MAX_INPUT_BYTES`**: reject path-based inputs larger than this before invoking MarkItDown (default 50 MiB); failure reason `file_too_large`.
- **Logging**: logger name **`AdamI-DocumentParse`**; English markers **`[doc.parse] route=…`** include `markitdown_ok`, `markitdown_skipped`, `markitdown_rejected`, `markitdown_fail`, `fallback_to_unstructured`, `unstructured_ok`, `unstructured_fail`, `extract_none`.
- **i18n**: `doc.pipeline.step6`, `mmmd.log.markitdown_disabled` (when `ADAMI_MARKITDOWN_ENABLED=false`).
- **Tests**: `tests/test_document_parse_step6_config.py`.

### 中文（步骤 6：配置与可观测）

- **`ADAMI_MARKITDOWN_ENABLED`**：`True` 默认强制先尝试 MarkItDown；`None` 自动（能 import 才走）；`False` 关闭。
- **日志**：`AdamI-DocumentParse` + `[doc.parse] route=…` 便于检索排障。

---

## Step 7 (test matrix / CI / regression)

- **Module**: `tests/test_markitdown_bridge.py` (pytest-asyncio, `tmp_path` fixtures).
- **Mock matrix (no `unstructured` pip)**: inject a minimal **`unstructured`** stub via `sys.modules` so `MultiModalInput` enables the partition path; monkeypatch **`convert_document_path_to_markdown`** to return **`CONVERSION_FAILED`**, **`TIMEOUT`**, or **`FILE_TOO_LARGE`**; assert **`raw_multi_modal`** body contains the stub partition marker.
- **Real MarkItDown (one extension)**: **`test_bridge_real_docx_markitdown_roundtrip`** uses `pytest.importorskip("markitdown")` and a tiny OOXML `.docx` (covers one of the four whitelist suffixes; pdf/pptx/xlsx remain covered in `tests/test_document_markdown.py` when the extra is installed).
- **CI**: parallel job **`markitdown-bridge`** — `poetry install -E markitdown` then `pytest tests/test_markitdown_bridge.py` (see root **`ci.yml`** and **`.github/workflows/kernel-ci.yml`**). Default **`compliance-and-test`** job keeps `poetry install` without the extra; the real-convert row may **skip** there while mock rows still run.
- **Pytest marker**: `markitdown_bridge` (see `pyproject.toml`).
- **i18n**: `doc.pipeline.step7`.

### PR checklist (document pipeline / MarkItDown)

- [ ] At least **one** of the four whitelisted extensions has a **real** MarkItDown path exercised in CI (**`markitdown-bridge`** job: `.docx` in `test_markitdown_bridge.py`) or locally with `poetry install -E markitdown`.
- [ ] **Failure → fallback** is covered by **mock** MarkItDown + stub unstructured (`tests/test_markitdown_bridge.py`), so regressions in Step 3 wiring do not depend on installing `unstructured` in the default CI image.

### 中文（步骤 7：测试矩阵与 CI）

- **默认 CI**：可不装 `unstructured`；用 **mock + sys.modules 桩** 验证失败回退。
- **独立 job**：安装 **`markitdown` extra** 跑真 **docx** 与全文件矩阵。

---

## Step 8 (release notes / migration — communication only)

- **No root `CHANGELOG`**: this repository documents document-pipeline releases in **README** → section **Optional capabilities — document pipeline (Step 8)** and this file.
- **What to communicate in PRs** (copy for reviewers): optional **`markitdown`** extra; **Markdown-first** when the extra is installed and auto/force flags allow it; **rollback** via `ADAMI_MARKITDOWN_ENABLED=false` and log grep `AdamI-DocumentParse` / `[doc.parse] route=`; **skills** aligned to kernel API (no production sandbox MarkItDown CLI).
- **i18n**: `doc.pipeline.step8`.
- **Design output (cross-cutting)**: `docs/design_output_policy.md` + `docs/reference/awesome-design-systems.md`; prepended only when `call_llm(..., apply_design_output_policy=True)` (chat + Report Studio; see `cortex/design_output_policy.py`); i18n `doc.pipeline.design_output`.

### 中文（步骤 8：发布说明与迁移）

- 无根目录 **CHANGELOG**；以 README「可选能力」与本节为准；PR 描述可复制验证步骤。

## Change log

- **Step 0**: Baseline written; runtime code unchanged.
- **Step 1**: `pyproject.toml` + `poetry.lock` optional extra `markitdown`; README Quickstart; this section; i18n `doc.pipeline.step1`.
- **Step 2**: `document_markdown.py` bridge; README + cortex README; i18n `doc.pipeline.step2`; dev test helper dep `reportlab` for PDF fixtures in `tests/test_document_markdown.py`.
- **Step 3**: `multi_modal._process_file` MarkItDown-first + unstructured fallback; i18n `mmodal.file.missing_unstructured`, `mmmd.log.file_markdown`, `mmmd.log.markitdown_unavailable`, `mmmd.warn.markitdown_fallback`, `doc.pipeline.step2`/`step3`; `tests/test_multi_modal_document_path_step3.py`.
- **Step 4**: `DecisionProcessor` intake before multimodal + `_intake_archive_body_from_payload`; i18n `doc.pipeline.step4`, `dcpu.log.intake_markdown`, `dcpu.warn.intake_doc_extract`; `tests/test_intake_archive_step4.py`.
- **Step 5**: Skills docs (`skills/skills/pptx/` etc.) kernel-first for Markdown; MarkItDown CLI dev-only; i18n `doc.pipeline.step5`; acceptance in `tests/test_acceptance_document_pipeline_steps_0_1.py`.
- **Step 6**: `ADAMI_MARKITDOWN_ENABLED` / timeout / max input bytes; logger `AdamI-DocumentParse`; i18n `doc.pipeline.step6`, `mmmd.log.markitdown_disabled`; `tests/test_document_parse_step6_config.py`.
- **Step 7**: `tests/test_markitdown_bridge.py`; CI job `markitdown-bridge`; pytest marker `markitdown_bridge`; i18n `doc.pipeline.step7`.
- **Step 8**: README *Optional capabilities — document pipeline*; migration bullets; i18n `doc.pipeline.step8`.
