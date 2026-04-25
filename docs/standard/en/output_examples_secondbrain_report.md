# Output examples — SecondBrain Markdown + Report Studio

**Audience**: operators who want a **copy-paste golden path** from kernel behavior to **on-disk `.md` artifacts** under the SecondBrain tree.

**Chinese mirror (information-equivalent)**: [`../zh/output_examples_secondbrain_report.md`](../zh/output_examples_secondbrain_report.md).

---

## Block A — SecondBrain Markdown on disk

### A.1 Where the tree lives

1. Root: **`settings.path_second_brain_root`**, overridable with **`ADAMI_SECOND_BRAIN_ROOT`** (defaults under `ADAMI_DATA_DIR/brain` when unset). See [knowledge_wiki_second_brain.md](knowledge_wiki_second_brain.md).

### A.2 Intake path (documents → Inbox)

1. **`DecisionProcessor`** routes **`INTAKE` / `INTAKE_AUTO`** to **`_handle_intake_action`** (`src/adami_kernel/cortex/decision_processor.py`). When the pipeline archives document output, it lands under PARA (commonly **`Inbox/`**) as Markdown with frontmatter—see the document pipeline docs for `file_path` / `body_format: markdown`.

### A.3 Report Studio persistence (`source="report_studio"`)

1. **`_handle_report_action`** (same module) runs **`/report …`** subcommands. On **`/report run <daily|weekly|monthly>`**, it calls **`generate_fixed_blocks_report`** (`src/adami_kernel/peripheral/report_studio/report_generator.py`), then persists via **`SecondBrainManager`**:
   - **`write_resource_note(...)`** when **`ReportConfig.write_to == "Resources"`**;
   - **`write_inbox_note(...)`** when **`write_to == "Inbox"`** (default in `ReportConfig`).
2. Both helpers live in **`src/adami_kernel/hippocampus/second_brain.py`** (ingest layer: **`second_brain_ingest.write_note`**). Calls pass **`source="report_studio"`** and a **`dedupe_key`** so repeated runs the same day can collapse to one logical note.
3. On disk you should see files similar to **`Inbox/report-YYYY-MM-DD-… .md`** (prefix from **`note_prefix`**, default `report`). Your `.adami_data/brain/Inbox/report-*.md` samples follow this pattern.

### A.4 Report configuration files

1. **`ReportConfigStore`** (`src/adami_kernel/peripheral/report_studio/report_store.py`) reads/writes JSON under:

   `{brain_root}/System/working-memory/report_configs/{daily|weekly|monthly}.json`

2. **`ReportConfig`** (`report_config.py`) fields include **`enabled`**, **`schedule`** (`timezone`, `publish_time_hhmm`, …), **`sections`** (top_n per block), **`write_to`** (`"Inbox"` | `"Resources"`), **`note_prefix`**.

---

## Block B — Report Studio CLI / Telegram / Discord

### B.1 Prerequisites

1. Running kernel (or any path that reaches **`DecisionProcessor._handle_report_action`**) with **`second_brain`** wired on the kernel object.
2. **`ReportConfigStore.ensure_defaults()`** creates missing JSON configs on first access.
3. **Optional richer sections**: **`toolbox.web`** (DuckDuckGo search) improves news-style blocks; **`kernel.router`** enables **`call_llm`** translation path used in report generation. If web or keys are missing, **sections may be empty**—the Markdown file is still written; body uses i18n placeholders such as **`report.studio.empty_*`** keys where providers return no rows.

### B.2 Commands (same text, different transport)

1. **`/report help`** (or bare **`/report`**) → shows **`dp.report.*`** help body from i18n.
2. **`/report list`** → lists `daily` / `weekly` / `monthly` configs with paths.
3. **`/report show daily|weekly|monthly`** → dumps the JSON config (sanitized by UI).
4. **`/report set daily|weekly|monthly <JSON>`** → merges into the on-disk config (must stay under brain root).
5. **`/report run daily|weekly|monthly`** → generates HTML/Markdown internally, **writes SecondBrain note**, then pushes a **plain-text** excerpt to the chat:
   - **Discord**: shorter chunk budget (~1800 chars per chunk).
   - **Telegram**: ~3800 chars per chunk.
   - **CLI / other**: larger budget; see **`plain_report_text_for_im_channels`** in `report_port_format.py`.

### B.3 Golden path (happy path)

1. Ensure **`enabled: true`** for the chosen type in the JSON config (or enable via **`/report set …`**).
2. Send: **`/report run daily`** (or **`weekly`** / **`monthly`**).
3. Expect:
   - Chat: header from **`dp.report.push_header`**, then chunked text (may be short if sections empty).
   - Disk: new or updated **`…/Inbox/report-… .md`** (or **`Resources/…`** if `write_to` is **`Resources`**).
   - Optional log / reply line with **`dp.report.generated_path`** including the absolute `path`.

### B.4 When sections look “empty”

1. **No network / blocked search**: web-backed blocks may resolve to empty lists; rendered Markdown still contains section headers with **empty** copy driven by **`report.studio.empty_world_news`**, **`empty_ai`**, etc.—this is **normal**, not a failed write.
2. **`enabled: false`**: **`/report run`** replies with **`dp.report.disabled`** and **does not** write a new note for that type.

---

## Related reading

1. [profiles_shared_brain.md](profiles_shared_brain.md) — shared brain vs per-workflow state.
2. [ARCHITECTURE.md](ARCHITECTURE.md) — Cortex / Nexus topology.
3. `docs/document_parsing_baseline_step0.md` — intake + Markdown pipeline (Step 4).

---

**Document baseline**: refresh SHA256 in `docs/internal/phase0_document_baseline.md` when this file is materially edited, or record the new hash in your PR description.
