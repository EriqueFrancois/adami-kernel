## Purpose

`cortex/` owns “thinking and routing”:

- hybrid LLM routing (local-first with cloud acceleration)
- intent routing
- decision processing for `system.events`
- prompt construction and tool routing glue

## Key files

- `router.py`: `HybridLLMRouter` (local fallback + cloud providers, unified tracing shim).
- `decision_processor.py`: consumes events and dispatches actions, delegates complex tasks to Planner.
- `intent_router.py`: intent classification/routing layer.
- `prompt.py`: builds prompts used by decision/orchestration logic.
- `evolution.py`: `EvolutionEngine` integration glue (skills, tool schemas, builders).
- `multi_modal.py`: multimodal handling; documents: **MarkItDown-first** (four suffixes via `document_markdown.py`) then optional **`unstructured.partition`** (see `docs/document_parsing_baseline_step0.md` Step 3).
- `document_markdown.py`: async MarkItDown bridge (`enable_plugins=False`), whitelisted office/pdf formats; optional extra `markitdown`.
- `self_model.py`: self-model state.
- `tools/`: parsing utilities and helpers (e.g. JSON extraction).
- `tools_manager.py`: tool execution façade (includes LLM router access).

## Primary flows

- `core/lifecycle_manager.py` → `decision_processor.process(...)`
- decision → direct answer / tool call / **Planner orchestration**

## Operational notes

- `router.py` is intentionally defensive: upstream callers should not crash on LLM provider errors.

## Document attachments (Steps 0–8)

- **Ingress**: `media_type == "document"` → `MultiModalInput._process_file` (MarkItDown path when extra installed + suffix allowed, else `unstructured.partition` when import succeeds).
- **Egress to user**: `DecisionProcessor._dispatch_multimodal_task` turns `raw_multi_modal` into one **`call_llm`** pass using `dp.multimodal.doc_analyst_prompt` (truncated raw body).
- **Intake**: `_handle_intake_action` writes Inbox notes; with **`payload.file_path`** it calls **`toolbox.multi_modal.process_input("document", …)`** (same path as `_process_file`) and archives **Markdown** `raw_content` when available; otherwise the **task** string. See **`docs/document_parsing_baseline_step0.md`** (Step 4) and **`doc.pipeline.step4`**.
- **Skills (SSOT)**: repository skills should call **`document_markdown`** / **`convert_document_path_to_markdown`** on the kernel host—not duplicate MarkItDown installs in sandboxes; see Step 5 in **`docs/document_parsing_baseline_step0.md`** and **`doc.pipeline.step5`**.
- **Ops (Step 6)**: **`Settings`** fields **`ADAMI_MARKITDOWN_ENABLED`** (True=default force attempt, None=auto if importable, False=off), **`ADAMI_DOCUMENT_MARKDOWN_TIMEOUT_SEC`**, **`ADAMI_DOCUMENT_MARKDOWN_MAX_INPUT_BYTES`**; **`AdamI-DocumentParse`** logs **`[doc.parse] route=…`** for which extractor path ran. See **`doc.pipeline.step6`**.
- **Regression (Step 7)**: **`tests/test_markitdown_bridge.py`** + CI job **`markitdown-bridge`** (`poetry install -E markitdown`); **`doc.pipeline.step7`**.
- **Release / migration (Step 8)**: no root **`CHANGELOG`** — see repo **README** section *Optional capabilities — document pipeline* and **`doc.pipeline.step8`**.
- **Design output**: **`docs/design_output_policy.md`** (injected when **`call_llm(..., apply_design_output_policy=True)`** — chat + Report Studio); index snapshot **`docs/reference/awesome-design-systems.md`**; **`doc.pipeline.design_output`**.

