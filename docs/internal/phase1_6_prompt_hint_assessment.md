# Phase 1.6.1 — Prompt knowledge-wiki hint (technical assessment)

**Conclusion**: **Do** implement optional hints (defaults **on** in `config.py` when SecondBrain is present; operators may disable via env).

**Rationale**

1. `PromptBuilder.build_action_prompt` (`src/adami_kernel/cortex/prompt.py`) is the single assembly point for action prompts used from `DecisionProcessor` (see `build_action_prompt` call path). Appending one short line after SecondBrain identity/doctrine injection keeps behavior localized and auditable.
2. Token budget: when disabled, hints add **zero** tokens. When enabled, `cprm.hint.knowledge_wiki_priority` plus `doc.pipeline.output_examples_report` are appended (each gated by its own setting).
3. Gating: append only when **`second_brain` is non-None** and the setting is true—otherwise the hint would contradict runtime (no archive to prefer).

**Implementation**: Phase 1.6.2 (`config.py`, `.env.example`, `prompt.py`, locales, tests).
