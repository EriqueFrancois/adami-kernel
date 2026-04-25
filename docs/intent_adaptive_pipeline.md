# Intent adaptive pipeline (tiered classification)

This document describes the **intent adaptive** subsystem: classify user text into a
finite behavioral space, route to **preset templates** when confident, otherwise
**clarify** or fall back to the existing **dynamic** path (Planner / `WorkflowEngine`).

## Glossary

- **IntentFamily** — Coarse bucket (`system`, `retrieval`, `synthesis`, `planning`,
  `action`, `conversation`, `unknown`). Evolve only with explicit versioning notes.
- **IntentType** — Wire string id for a fine-grained template or handler key
  (e.g. `retrieval.weather`). Open-ended; constants live in `IntentType` in code.
- **IntentClassificationResult** — Structured output: `primary_family`,
  `primary_type`, `confidence`, flat `slots`, `route` (`template` | `dynamic` |
  `clarify`), and `reason_codes` for telemetry.
- **Tier** — Rule-based classifier (fast) → optional LLM classifier → template
  registry → existing AdamI pipeline (implemented in later steps).

## Relationship to the EventBus (text diagram)

```
CLI / Discord / Telegram / Web
        │
        ▼
   EventBus.publish( AdamiEvent → topic "system.events" )
        │
        ▼
   LifecycleManager.event_consumer()
        │
        ▼
   DecisionProcessor  ──►  intent_adaptive tier (``ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED``)
        │                      │
        │                      ├─► rules → optional LLM → ``TemplateRegistry.resolve``
        │                      ├─► template ``_send_reply`` (no handoff)
        │                      └─► fallback → Planner / SkillComposer / WorkflowEngine
        ▼
   (unchanged paths: SYSTEM_ACTION, /report, etc.)
```

Step 1 only adds **shared models** under `src/adami_kernel/cortex/intent_adaptive/`.
**Step 5** adds optional runtime wiring in `DecisionProcessor` (default **off**), so
default kernel behaviour remains Planner-first for `COMPLEX_TASK`.

## Step 1 deliverables

- `models.py` — Pydantic schemas and enums.
- `tests/test_intent_adaptive_models.py` — import and validation smoke tests.

See `README.md` (section **Intent adaptive pipeline (Steps 1–5)**) for the entry pointer.

## Step 2 deliverables

- `outcomes.py` — `TemplateOutcome` (`reply_markdown`, `telemetry`, `handoff_to_dynamic`).
- `template_registry.py` — `IntentTemplateHandler` protocol, `TemplateExecutionContext`
  (narrow ports: `send_reply`, `router_call_llm`, `web_search`), `TemplateRegistry.register`
  / `resolve`, and `NoOpTemplateHandler`.
- `tests/test_intent_adaptive_registry.py` — scoring, `None` when no match, tie-break.

No `LifecycleManager` / `DecisionProcessor` changes in Step 2.

## Step 4 deliverables (optional LLM JSON classifier)

- `llm_classifier.py` — `build_intent_classification_llm_prompt`, `parse_llm_classification_json`,
  `maybe_llm_classify_after_rule`, `maybe_llm_classify_with_settings`.
- `config.py` — `ADAMI_INTENT_LLM_CLASSIFIER_ENABLED` (default `False`),
  `ADAMI_INTENT_CLASSIFIER_MIN_CONFIDENCE`, `ADAMI_INTENT_CLASSIFIER_TIMEOUT_SEC`.
- `tests/test_intent_adaptive_llm_classifier.py` — mock `call_llm`: valid JSON, fenced JSON,
  parse failure, timeout, disabled / strong-rule short-circuit.

No `DecisionProcessor` wiring in Step 4.

## Step 4.1 — Multi-label merge policy

- `models.py` — optional `secondary_types` (wire ids) and `family_candidates` (JSON alias
  `families`) on `IntentClassificationResult`.
- `merge_policies.py` — `apply_family_merge_policy`: **system** label wins over all others;
  **action** is demoted to **`clarify`** (or **`unknown`** if action-only) unless
  `ADAMI_INTENT_ACTION_PERMISSION_GRANTED` is true (see `config.py`).
- `llm_classifier.py` — runs merge after every successful JSON parse.
- `tests/test_intent_adaptive_merge_policies.py` — conflict table.
- i18n **`intent.clarify.prompt`** for user-facing clarification text.

## Step 4.1 — Acceptance test plan

Automated checks live in `tests/test_intent_adaptive_step41_acceptance.py` plus
`tests/test_intent_adaptive_merge_policies.py`.

**S41-A. Package surface**

- S41-A1: `apply_family_merge_policy` is exported from `adami_kernel.cortex.intent_adaptive`.

**S41-B. Schema**

- S41-B1: `IntentClassificationResult` accepts `secondary_types` and `family_candidates`;
  JSON key **`families`** maps to `family_candidates` on parse.
- S41-B2: Invalid `secondary_types` entries fail validation.

**S41-C. Merge invariants**

- S41-C1: **system** in the candidate set forces `primary_family=system`, clears
  `family_candidates`, `route=dynamic`, and appends `merge_family_system_wins`.
- S41-C2: **action** without permission demotes per the conflict table (including
  action-only → `unknown` + `clarify` + `merge_action_rejected`).
- S41-C3: **action** with `action_permission_granted=True` keeps primary and strips
  duplicate candidates.

**S41-D. Serialization**

- S41-D1: `model_dump` / `model_validate` preserves `secondary_types` and
  `family_candidates` for telemetry round-trips.

**S41-E. Configuration**

- S41-E1: `ADAMI_INTENT_ACTION_PERMISSION_GRANTED` defaults to `False` in `Settings`.

**S41-F. LLM pipeline integration**

- S41-F1: `maybe_llm_classify_after_rule` applies merge on successful JSON (mocked
  `call_llm` returning a payload with `families`).

**S41-G. i18n**

- S41-G1: `intent.clarify.prompt` and `doc.intent_adaptive.step41_merge` are non-empty
  in `en` / `zh-Hans` and differ by locale.

**S41-H. Documentation**

- S41-H1: `README.md` references merge policy keywords (`merge`, `ADAMI_INTENT_ACTION_PERMISSION_GRANTED`,
  or `doc.intent_adaptive.step41_merge`).

## Step 3 deliverables (Phase 1: rule-only)

- `rule_classifier.py` — `rule_classify_after_router(task_text, router_tag=..., router_data=...)`
  returns `IntentClassificationResult` only for `router_tag == "COMPLEX_TASK"`, with
  bounded `RULE_CONFIDENCE_MAX` and English-coded `reason_codes` (`rule_based`, …).
  Skips lines starting with `/report`. Does **not** change `SemanticIntentRouter.route_task`.
- `tests/test_intent_adaptive_rule_classifier.py` — `/report list` stays non-rule for
  `SYSTEM_ACTION` / `DIRECT_ANSWER`; `/report` leader suppressed even if mis-tagged
  `COMPLEX_TASK`; sample keyword hits.

## Step 1 — Acceptance test plan

Automated checks live in `tests/test_intent_adaptive_step1_acceptance.py` (execute with
`pytest` below). Manual / doc checks are listed for reviewers.

**A. Contract and packaging**

- A1: `import adami_kernel.cortex.intent_adaptive` resolves; `__all__` exports match
  imports used by downstream steps.
- A2: Every `IntentFamily` member has a distinct stable wire value (lowercase string).

**B. Pydantic validation (`IntentClassificationResult`)**

- B1: Valid instances with `confidence` at `0.0` and `1.0` (boundary).
- B2: Reject `confidence` outside `[0, 1]`; reject empty `primary_type`; reject
  unknown fields (`model_config.extra = "forbid"`).
- B3: Reject invalid `route` literals (only `template`, `dynamic`, `clarify`).
- B4: `slots` keys must match snake_case ASCII (`^[a-z][a-z0-9_]*$`); reject
  `CamelCase`, leading digit, hyphen.

**C. Serialization (telemetry / future HTTP)**

- C1: `model_dump()` round-trips through `model_validate()` without loss for a
  representative payload.

**D. Factory**

- D1: `default_unknown_result()` returns `UNKNOWN` family/type, `confidence` 0,
  optional `reason_codes` override.

**E. Repository hygiene**

- E1: `README.md` references `docs/intent_adaptive_pipeline.md`.
- E2: i18n keys `doc.intent_adaptive.overview` and `doc.intent_adaptive.step1_models`
  exist and are non-empty in both `en` and `zh-Hans` `common.json`.

**Commands (CI-friendly)**

```bash
python -m compileall -q src/adami_kernel/cortex/intent_adaptive
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest \
  tests/test_intent_adaptive_models.py \
  tests/test_intent_adaptive_step1_acceptance.py \
  tests/test_intent_adaptive_registry.py \
  tests/test_intent_adaptive_step2_acceptance.py \
  tests/test_intent_adaptive_rule_classifier.py \
  tests/test_intent_adaptive_step3_acceptance.py \
  tests/test_intent_adaptive_llm_classifier.py \
  tests/test_intent_adaptive_step4_acceptance.py \
  tests/test_intent_adaptive_merge_policies.py \
  tests/test_intent_adaptive_step41_acceptance.py \
  tests/test_intent_adaptive_step5_acceptance.py \
  tests/test_decision_processor_intent_adaptive_smoke.py \
  tests/test_intent_adaptive_step51_acceptance.py \
  tests/test_intent_adaptive_step6_acceptance.py \
  tests/test_intent_adaptive_step6_e2e_templates.py \
  tests/test_i18n_locale_key_parity.py -q
```

**Note (Step 9):** the canonical **offline** bundle for day-to-day intent-adaptive verification is
``pytest tests/test_intent_adaptive_* tests/test_i18n_locale_key_parity.py -q`` (also executed as a
named CI step; see § Step 9).

## Step 4 — Acceptance test plan

Automated checks live in `tests/test_intent_adaptive_step4_acceptance.py` plus
`tests/test_intent_adaptive_llm_classifier.py`.

**S4-A. Package surface**

- S4-A1: `maybe_llm_classify_after_rule`, `maybe_llm_classify_with_settings`,
  `build_intent_classification_llm_prompt`, and `parse_llm_classification_json` are
  exported from `adami_kernel.cortex.intent_adaptive`.

**S4-B. Default configuration**

- S4-B1: `Settings` defaults: `ADAMI_INTENT_LLM_CLASSIFIER_ENABLED is False`,
  `ADAMI_INTENT_CLASSIFIER_MIN_CONFIDENCE == 0.55`,
  `ADAMI_INTENT_CLASSIFIER_TIMEOUT_SEC == 8.0`.

**S4-C. LLM call discipline**

- S4-C1: When the LLM path runs, `call_llm` receives `apply_design_output_policy=False`,
  `skip_design_output_policy=True`, and `temperature=0.1`.

**S4-D. Degradation**

- S4-D1: Invalid JSON and invalid schema (e.g. unknown `primary_family`) yield
  `UNKNOWN` + `llm_classifier_parse_error` in `reason_codes` (timeouts covered in the
  unit module).

**S4-E. i18n**

- S4-E1: `intent.classifier.parse_error` and `intent.classifier.unavailable` are
  non-empty in `en` / `zh-Hans` and differ by locale; `doc.intent_adaptive.step4_llm_classifier`
  differs between locales.

**S4-F. Repository hygiene**

- S4-F1: `README.md` names `ADAMI_INTENT_LLM_CLASSIFIER_ENABLED` and
  `doc.intent_adaptive.step4_llm_classifier`.
- S4-F2: `config.py` contains the three `ADAMI_INTENT_*` field names.

**S4-G. Settings wrapper**

- S4-G1: `maybe_llm_classify_with_settings(..., settings=settings)` does not call
  `call_llm` when the default `ENABLED` flag is false (parity with Step 3-only flow).

**S4-H. JSON contract**

- S4-H1: `parse_llm_classification_json` accepts fenced ```json blocks and validates
  to `IntentClassificationResult`.

**S4-I. Prompt vocabulary**

- S4-I1: `build_intent_classification_llm_prompt` embeds required JSON key names and
  representative `IntentFamily` wire ids.

**S4-J. Regression (`test_intent_adaptive_llm_classifier.py`)**

- S4-J1: Valid / fenced JSON, disabled path, strong-rule short-circuit, timeout, and
  non-`COMPLEX_TASK` guard remain green.

## Step 3 — Acceptance test plan

Automated checks live in `tests/test_intent_adaptive_step3_acceptance.py` plus
`tests/test_intent_adaptive_rule_classifier.py`.

**S3-A. Public API**

- S3-A1: `rule_classify_after_router` and `RULE_CONFIDENCE_MAX` are exported from
  `adami_kernel.cortex.intent_adaptive` and `RULE_CONFIDENCE_MAX == 0.6`.

**S3-B. Result shape**

- S3-B1: Any non-`None` rule hit uses `confidence == RULE_CONFIDENCE_MAX`, `route ==
  "dynamic"`, and `reason_codes` contains `rule_based` plus a `rule_hit_*` tail.

**S3-C. Router tag gate**

- S3-C1: For non-`COMPLEX_TASK` tags (including empty string), rule tier returns
  `None` even when the text contains weather/crypto keywords.

**S3-D. `/report` guard**

- S3-D1: Lines starting with `/report` return `None` when `router_tag` is
  `COMPLEX_TASK` (mis-route safety).

**S3-E. Heuristic precedence**

- S3-E1: When multiple keyword families appear, the implementation order in
  `rule_classifier.py` wins (e.g. weather before crypto).

**S3-F. i18n**

- S3-F1: `doc.intent_adaptive.rule_tier` exists, is non-empty in `en` and `zh-Hans`,
  and English ≠ Chinese.

**S3-G. Documentation**

- S3-G1: `README.md` references `doc.intent_adaptive.rule_tier` and Phase 1 / rule API.
- S3-G2: `intent_router.py` class docstring mentions `intent_adaptive` and
  `rule_classify_after_router`.

**S3-H. Edge inputs**

- S3-H1: Empty or whitespace-only `task_text` under `COMPLEX_TASK` → `None`.

**S3-I. Greeting regex**

- S3-I1: Full-line short greetings classify as `CONVERSATION_GREETING`; a greeting
  plus extra text does not match.

**S3-J. Regression bundle (`test_intent_adaptive_rule_classifier.py`)**

- S3-J1: `/report list` with `SYSTEM_ACTION` / `DIRECT_ANSWER` → `None`; `/report list`
  with `COMPLEX_TASK` → `None`; representative keyword paths return expected families.

## Step 2 — Acceptance test plan

Automated checks live in `tests/test_intent_adaptive_step2_acceptance.py` plus
`tests/test_intent_adaptive_registry.py`.

**S2-A. Package surface**

- S2-A1: `__all__` includes `TemplateRegistry`, `IntentTemplateHandler` exports
  (`NoOpTemplateHandler`, `TemplateExecutionContext`, `TemplateOutcome`) and each
  resolves on `import adami_kernel.cortex.intent_adaptive`.

**S2-B. `TemplateOutcome`**

- S2-B1: Default instance has empty `reply_markdown`, empty `telemetry`, and
  `handoff_to_dynamic is False`.

**S2-C. `TemplateExecutionContext`**

- S2-C1: Required fields only; optional ports default to `None`.

**S2-D. `TemplateRegistry.resolve` and `min_match_score`**

- S2-D1: With `min_match_score=0.7`, a handler returning `0.65` yields `None`;
  returning `0.71` yields a handler.

**S2-E. `register()`**

- S2-E1: Whitespace around `intent_type` is stripped; empty / whitespace-only
  `intent_type` raises (`tests/test_intent_adaptive_registry.py`).

**S2-F. `NoOpTemplateHandler`**

- S2-F1: `match_score` is `0.0`; `execute` sets `handoff_to_dynamic` and records
  `trace_id` in `telemetry`.

**S2-G. Diagnostics**

- S2-G1: `registered_pairs()` reflects registration order and updates when new
  handlers are added.

**S2-H. Repository hygiene**

- S2-H1: `README.md` mentions Step 2 / `TemplateRegistry` and the Step 2 doc i18n key.
- S2-H2: `doc.intent_adaptive.step2_template_registry` and `intent.template.no_match`
  are present and non-empty in `en` and `zh-Hans`; English and Chinese doc strings differ.

**S2-I. Scoring regression (registry unit tests)**

- S2-I1: Highest `match_score` wins; all-zero scores → `None`; equal scores → first
  registered handler wins (`tests/test_intent_adaptive_registry.py`).

## Step 5 deliverables (DecisionProcessor orchestration)

- `config.py` — `ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED` (default `False`),
  `ADAMI_INTENT_ADAPTIVE_FALLBACK_NOTICE` (default `False`).
- `decision_processor.py` — `_maybe_route_intent_adaptive` runs inside
  `_dispatch_complex_task` before `TaskPlanner.plan_and_execute` (rules → optional LLM
  → `TemplateRegistry.resolve` → `_send_reply` or clarify copy, else Planner). **Step 7:**
  same hook returns `(handled, intent_adaptive_meta)` and passes non-`None` meta to the
  Planner as optional telemetry (see § Step 7).
- `component_initializer.py` — builds `components["intent_template_registry"]`
  (`TemplateRegistry` + placeholder `NoOpTemplateHandler`).
- `lifecycle_manager.py` — `self.intent_template_registry` from components.
- `kernel_context.py` — `intent_template_registry` on the `KernelContext` contract.
- `tests/test_decision_processor_intent_adaptive_smoke.py` — Planner vs template smoke.
- i18n — `doc.intent_adaptive.step5_decision_wiring`, `intent.adaptive.user.fallback_to_planner`.

## Step 5 — Acceptance test plan

Automated checks live in `tests/test_intent_adaptive_step5_acceptance.py` plus
`tests/test_decision_processor_intent_adaptive_smoke.py`.

**S5-A. Configuration defaults**

- S5-A1: `ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED is False` and
  `ADAMI_INTENT_ADAPTIVE_FALLBACK_NOTICE is False` on `Settings`.

**S5-B. Decision surface**

- S5-B1: `DecisionProcessor` exposes async `_maybe_route_intent_adaptive`.
- S5-B2: With the pipeline flag off, `_maybe_route_intent_adaptive` returns `(False, None)`
  without invoking `Planner` (stub kernel / `asyncio.run`).

**S5-C. Component factory**

- S5-C1: `ComponentInitializer.initialize_components` returns a non-``None``
  ``intent_template_registry`` that is a ``TemplateRegistry`` instance.
  (Automated test imports the full initializer graph; it is skipped when optional
  deps such as ``aiosqlite`` are not installed in the active interpreter.)

**S5-D. Orchestration smoke**

- S5-D1: Pipeline **on** + rule-strong weather text + registered template handler →
  `plan_and_execute` **not** called; user reply contains template body.
- S5-D2: Pipeline **on** + text with no rule hit → Planner `plan_and_execute` runs.
- S5-D3: Pipeline **off** → Planner runs even when a template would match (legacy path).

**S5-E. i18n**

- S5-E1: `doc.intent_adaptive.step5_decision_wiring` and
  `intent.adaptive.user.fallback_to_planner` are non-empty in `en` / `zh-Hans` and
  differ by locale (doc + user strings).

**S5-F. Documentation**

- S5-F1: `README.md` references `ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED` and
  `doc.intent_adaptive.step5_decision_wiring`.

## Step 5.1 deliverables (observability / audit)

- `telemetry.py` — stable span keys `intent.family`, `intent.type`, `intent.confidence`,
  `intent.route` plus `record_intent_classification_on_span` / `intent_span_attributes_dict`.
- `decision_processor.py` — passes the active `decision_processor.process` span into
  `_dispatch_complex_task` / `_maybe_route_intent_adaptive`; DEBUG log line includes
  `route=` after the `[intent_adaptive]` prefix.
- `tests/test_intent_adaptive_step51_acceptance.py` — Step 5.1 acceptance (span keys,
  `set_attribute` bridge, DEBUG `[intent_adaptive]` grep, i18n, README, exports).
- i18n — `doc.intent_adaptive.step51_observability`, `doc.operator.intent_adaptive_grep`.

## Step 5.1 — Acceptance test plan

Automated checks live in `tests/test_intent_adaptive_step51_acceptance.py`.

**S51-A. Span keys**

- S51-A1: Constants match `intent.family`, `intent.type`, `intent.confidence`, `intent.route`.

**S51-B. Span bridge**

- S51-B1: `intent_span_attributes_dict` returns the four keys with correct wire values.
- S51-B2: `record_intent_classification_on_span` invokes `set_attribute` on a span
  mock with the four keys.
- S51-B3: Setter exceptions from `set_attribute` do not propagate.

**S51-C. Log audit**

- S51-C1: With pipeline enabled and a rule-strong weather task, DEBUG logs for
  `AdamI-DecisionProcessor` contain `[intent_adaptive]` and `route=`; the trace span
  mock receives `set_attribute` (span wiring from `DecisionProcessor`).

**S51-D. i18n**

- S51-D1: `doc.intent_adaptive.step51_observability` and `doc.operator.intent_adaptive_grep`
  are non-empty in `en` / `zh-Hans`.
- S51-D2: English and Chinese strings differ for both keys.

**S51-E. README**

- S51-E1: `README.md` references Step 5.1 observability (`doc.intent_adaptive.step51_observability`),
  logger `AdamI-DecisionProcessor`, log grep token `[intent_adaptive]`, and `intent.family`.

**S51-F. Package surface**

- S51-F1: `adami_kernel.cortex.intent_adaptive.__all__` includes telemetry symbols
  (`ATTR_INTENT_*`, `record_intent_classification_on_span`, `intent_span_attributes_dict`).

## Step 6 deliverables (first preset templates)

- `templates/retrieval_weather.py`, `templates/retrieval_crypto.py` — thin handlers:
  slot excerpt → ``ToolboxManager.web.search`` → Markdown bullets; optional ``call_llm``
  Markdown fallback; i18n stubs when both are empty. **No subprocess** in template modules.
- `templates/_web_snippets.py` — shared Markdown formatting for search hits.
- `bootstrap_templates.py` — ``register_builtin_intent_templates`` registers
  ``retrieval.weather`` and ``retrieval.crypto`` (kernel init, after noop).
- `template_registry.py` — ``TemplateExecutionContext.classification`` passes the
  winning ``IntentClassificationResult`` into ``execute``.
- `decision_processor.py` — wires ``web.search`` into ``TemplateExecutionContext.web_search``.
- `component_initializer.py` — calls ``register_builtin_intent_templates``.
- i18n — ``intent.help.body``, ``intent.help.supported_types``, ``intent.template.*`` titles/stubs.
- ``tests/test_intent_adaptive_step6_acceptance.py`` — registration, README/i18n, snippet helper,
  direct ``resolve`` + ``execute`` smoke.
- ``tests/test_intent_adaptive_step6_e2e_templates.py`` — full ``DecisionProcessor`` path (web hits + stub).

## Step 6 — Acceptance test plan

Automated checks live in ``tests/test_intent_adaptive_step6_acceptance.py`` plus
``tests/test_intent_adaptive_step6_e2e_templates.py``.

**S6-A. Registration**

- S6-A1: ``register_builtin_intent_templates`` registers handlers for
  ``IntentType.RETRIEVAL_WEATHER`` and ``IntentType.RETRIEVAL_CRYPTO`` (observable via
  ``registered_pairs()``).

**S6-B. E2E Markdown contract** (`test_intent_adaptive_step6_e2e_templates.py`)

- S6-B1: With pipeline on, mocked ``web.search`` hits, and a rule-strong **weather** utterance,
  ``_send_reply`` body contains ``<!-- intent-template:retrieval.weather -->`` and a ``##`` heading.
- S6-B2: Same for a **crypto** utterance and ``retrieval.crypto`` marker.

**S6-C. Stub fallback** (`test_intent_adaptive_step6_e2e_templates.py`)

- S6-C1: Empty search results still yield a template reply with the weather marker and ``##``
  (i18n stub path).

**S6-D. Snippet helper** (`test_intent_adaptive_step6_acceptance.py`)

- S6-D1: ``plain_lines_from_search_hits`` formats dict rows into plain-text lines.

**S6-E. README** (`test_intent_adaptive_step6_acceptance.py`)

- S6-E1: ``README.md`` lists ``retrieval.weather`` / ``retrieval.crypto`` and references
  ``doc.intent_adaptive.step6_templates`` plus bootstrap / ``register_builtin_intent_templates``.

**S6-F. i18n** (`test_intent_adaptive_step6_acceptance.py`)

- S6-F1: ``doc.intent_adaptive.step6_templates``, ``intent.help.*``, and ``intent.template.*`` keys
  are non-empty in ``en`` / ``zh-Hans``.
- S6-F2: English ≠ Chinese for ``intent.help.body`` and ``doc.intent_adaptive.step6_templates``.

**S6-H. Handler smoke** (`test_intent_adaptive_step6_acceptance.py`)

- S6-H1: ``TemplateRegistry.resolve`` returns the weather handler for a matching
  ``IntentClassificationResult``; ``execute`` yields Markdown containing the template marker
  and ``##`` (no ``web_search`` / ``call_llm`` in context — stub body path).

## Step 7 deliverables (dynamic handoff meta → Planner)

- ``handoff_meta.py`` — ``build_planner_handoff_meta`` / ``handoff_reason_for_planner_fallback``:
  JSON-safe English-key dict for optional ``intent_adaptive_meta``; includes
  ``dynamic_or_unknown_tail`` when ``route == "dynamic"`` or ``primary_family`` is ``UNKNOWN``.
- ``decision_processor.py`` — ``_maybe_route_intent_adaptive`` returns ``(handled, meta)``;
  on Planner fallback with a classification, ``meta`` is non-``None`` and forwarded to
  ``TaskPlanner.plan_and_execute(..., intent_adaptive_meta=...)`` only in that case.
- ``planner.py`` — ``plan_and_execute`` accepts optional keyword-only ``intent_adaptive_meta``;
  Step 7 logs it at DEBUG (truncated JSON). **Step 7.1** additionally injects the English
  ``Prior intent guess:`` line into planner-facing prompts (see § Step 7.1); workflow routing
  is unchanged.
- ``tests/test_intent_adaptive_step7_handoff_meta.py`` — meta present when pipeline on and
  template gate fails; absent when pipeline off; UNKNOWN family tail flag; low-confidence
  weather still reaches Planner without crash.

## Step 7 — Acceptance test plan

**S7-A. Meta wiring** (`test_intent_adaptive_step7_handoff_meta.py`)

- S7-A1: Pipeline on + rule/classification below ``ADAMI_INTENT_CLASSIFIER_MIN_CONFIDENCE`` (or
  no winning template) → ``plan_and_execute`` receives ``intent_adaptive_meta`` with
  ``handoff_kind``, ``handoff_reason``, ``route``, and (when applicable) ``dynamic_or_unknown_tail``.
- S7-A2: Pipeline off → ``plan_and_execute`` is called **without** the ``intent_adaptive_meta`` kwarg.

**S7-B. Regression**

- S7-B1: Low-confidence rule-strong weather text still invokes Planner once and ``_send_reply`` runs
  (no exception).

**S7-C. Documentation**

- S7-C1: ``README.md`` mentions Step 7 handoff / ``intent_adaptive_meta`` and points to this doc.

**S7-D. pytest**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_intent_adaptive_step7_handoff_meta.py -q
```

## Step 7.1 deliverables (Planner consumes ``intent_adaptive_meta``)

- ``handoff_meta.py`` — ``build_prior_intent_guess_english_line`` builds the single English line
  (``Prior intent guess: …``) from Step 7 meta keys.
- ``planner_prompts.py`` — ``GENERATE_PLAN_PROMPT`` and ``ANTHROPIC_SKILL_WRAPPER`` include an
  ``{intent_meta_block}`` slot (empty when no meta).
- ``planner.py`` — ``plan_and_execute`` stores ``intent_adaptive_prior_line`` in iteration
  ``context``; ``_generate_plan`` injects the block before the tool list; Anthropic skill path
  and ``try_mcp_agent_planner`` objective preamble receive the same line when present.
- i18n — ``doc.intent_adaptive.planner_hook`` (``en`` / ``zh-Hans``).
- ``tests/test_planner_intent_adaptive_meta_step71.py`` — substring / ordering asserts on prompts
  with vs without the prior-intent line; ``TaskPlanner._generate_plan`` integration capture.

## Step 7.1 — Acceptance test plan

**S71-A. Prompt shape** (`test_planner_intent_adaptive_meta_step71.py`)

- S71-A1: ``build_prior_intent_guess_english_line`` output starts with ``Prior intent guess:`` and
  contains ``route=``, ``family=``, ``prior_tier_handoff=``.
- S71-A2: ``GENERATE_PLAN_PROMPT`` with a non-empty ``intent_meta_block`` places the prior-intent
  line **before** the ``Task:`` user segment.
- S71-A3: Empty ``intent_meta_block`` → full prompt string does **not** contain ``Prior intent guess:``.

**S71-B. Planner integration**

- S71-B1: ``TaskPlanner._generate_plan(..., intent_meta_line=...)`` → ``router.call_llm`` prompt
  includes ``Prior intent guess:``; default ``intent_meta_line=""`` omits it.

**S71-C. i18n**

- S71-C1: ``doc.intent_adaptive.planner_hook`` non-empty in ``en`` / ``zh-Hans`` (covered by
  ``tests/test_intent_adaptive_step1_acceptance.py`` catalog row).

**S71-D. pytest**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_planner_intent_adaptive_meta_step71.py -q
```

(``TaskPlanner`` integration rows require optional deps such as ``aiosqlite``; use
``poetry run pytest …`` when the bare interpreter skips those tests.)

## Step 8 deliverables (config, safety, resource caps)

- ``config.py`` — ``ADAMI_INTENT_ADAPTIVE_LLM_PHASE_TIMEOUT_SEC`` (outer ``asyncio.wait_for`` around
  ``maybe_llm_classify_with_settings``), ``ADAMI_INTENT_TEMPLATE_EXECUTE_TIMEOUT_SEC`` (per
  ``IntentTemplateHandler.execute``), ``ADAMI_INTENT_ACTION_TEMPLATE_REQUIRES_CONFIRMATION`` (default
  ``True``): ACTION-family preset templates do not auto-run unless
  ``ADAMI_INTENT_ACTION_PERMISSION_GRANTED`` or ``router_data["intent_action_user_ack"]`` is set.
- ``decision_processor.py`` — applies the above timeouts and ACTION gate inside
  ``_maybe_route_intent_adaptive``.
- ``.env.example`` — English comments for the new ``ADAMI_INTENT_*`` knobs.
- i18n — ``intent.action_template.confirm_required``, ``intent.adaptive.template_execute_timeout``,
  ``doc.intent_adaptive.step8_guards`` (``en`` / ``zh-Hans``).
- ``tests/test_intent_adaptive_step8_guards.py`` — defaults, ACTION gate, template execute timeout,
  LLM outer timeout fallback, session_lock stress + sequential ``process()`` smoke.

## Step 8 — Acceptance test plan

**S8-A. Settings** (`test_intent_adaptive_step8_guards.py`)

- S8-A1: New timeout and ACTION-gate fields exist on ``Settings`` with safe defaults.

**S8-B. Timeouts**

- S8-B1: ``handler.execute`` exceeding ``ADAMI_INTENT_TEMPLATE_EXECUTE_TIMEOUT_SEC`` yields
  ``intent.adaptive.template_execute_timeout`` and does not hang the event loop indefinitely.
- S8-B2: Outer LLM phase ``wait_for`` fires while inner classify stalls; classification falls back
  to the rule tier (no deadlock).

**S8-C. ACTION template gate**

- S8-C1: ACTION + winning handler + no permission/ack → ``intent.action_template.confirm_required``,
  ``execute`` not invoked.
- S8-C2: Same with ``router_data.intent_action_user_ack=True`` → template ``execute`` runs.

**S8-D. Session lock**

- S8-D1: Many sequential acquire/release cycles leave the per-chat lock unlocked.
- S8-D2: Second acquire while held raises ``CancelledError`` (matches existing “busy” UX path).
- S8-D3: Sequential ``process()`` on ``DIRECT_ANSWER`` leaves no stuck lock; concurrent same-chat
  ``process()`` completes under a wall-clock bound without deadlock.

**S8-E. pytest**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_intent_adaptive_step8_guards.py -q
```

## Step 8.1 deliverables (ACTION + HITL one-shot ack)

- ``hitl_handler.py`` — ``grant_intent_action_template_ack`` / ``consume_intent_action_template_ack`` /
  ``prompt_intent_action_template_confirmation`` (Telegram inline buttons with ``intent_action_tpl:`` prefix).
- ``component_initializer.py`` — constructs the module singleton ``HitlHandler`` when it was ``None``,
  then injects ``telegram_nerve``.
- ``hitl_handler.initialize`` — subscribes to ``hitl.events`` only when ``ADAMI_ENABLE_HITL`` is true;
  intent ack state works even when the listener is skipped.
- ``decision_processor.py`` — consumes HITL ack before the ACTION gate; Telegram path may call
  ``prompt_intent_action_template_confirmation``; non-Telegram uses ``intent.action_template.hitl_fallback_body``.
- ``telegram_sensory.py`` — handles ``intent_action_tpl:approve|cancel:{chat_id}`` callbacks; guards
  ``hitl_handler`` before ``process_resume``.
- ``config.py`` — ``ADAMI_INTENT_ACTION_HITL_TELEGRAM`` (default ``True``).
- i18n — ``intent.action_template.hitl_*`` strings + ``doc.intent_adaptive.step81_hitl_action``.
- ``tests/test_intent_adaptive_step81_hitl_action.py`` — grant/consume, prompt wiring, pre-grant execute.

## Step 8.1 — Acceptance test plan

**S81-A. Ack state** (`test_intent_adaptive_step81_hitl_action.py`)

- S81-A1: ``grant`` + ``consume`` returns ``True`` once per chat id, then ``False``.

**S81-B. Telegram prompt**

- S81-B1: With a mocked ``telegram_nerve``, ``prompt_intent_action_template_confirmation`` calls
  ``send_interactive_buttons`` with callback_data containing ``intent_action_tpl:approve:{chat_id}``.

**S81-C. No ack → no execute**

- S81-C1: Covered by Step 8 ``test_action_family_template_blocked_without_ack_or_permission`` (execute
  mock not called).

**S81-D. Pre-grant → execute**

- S81-D1: ``hitl_handler.grant_intent_action_template_ack`` before ``_maybe_route_intent_adaptive`` →
  template ``execute`` runs once.

**S81-E. pytest**

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_intent_adaptive_step81_hitl_action.py -q
```

## Step 9 — Test matrix, degradation, and CI documentation

**Purpose:** give contributors a **repeatable offline verification** path: no outbound LLM
calls in CI for this area — tests inject **`AsyncMock`** / patch
``maybe_llm_classify_with_settings`` where the DecisionProcessor path would otherwise
touch the router. Future rows that need a live model must use ``@pytest.mark.integration``
(or a dedicated marker) and stay **out** of the Step 9 gate (today: none under
``tests/test_intent_adaptive_*``).

### Sequence (runtime, text)

```
User / channel adapter
        │
        ▼
EventBus.publish("system.events", AdamiEvent)
        │
        ▼
LifecycleManager.event_consumer ──► DecisionProcessor.process
        │
        ▼
_dispatch_complex_task (router_tag == COMPLEX_TASK)
        │
        ▼
_maybe_route_intent_adaptive  (only if ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED)
        │
        ├─► rule_classify_after_router
        │         │
        │         ▼
        ├─► maybe_llm_classify_with_settings  (only if ADAMI_INTENT_LLM_CLASSIFIER_ENABLED;
        │         │                              bounded by ADAMI_INTENT_ADAPTIVE_LLM_PHASE_TIMEOUT_SEC)
        │         ▼
        ├─► apply_family_merge_policy (multi-label / ACTION permission)
        │         │
        │         ▼
        ├─► intent_template_registry.resolve → match_score gate
        │         │
        │         ├─► route=clarify ──► intent.clarify.prompt → _send_reply (handled)
        │         ├─► ACTION template + confirmation gate ──► HITL prompt / fallback copy
        │         │         │                    OR grant/consume ack → execute
        │         ├─► winning template + confidence ≥ min ──► handler.execute (bounded)
        │         │         │                    └─► TemplateOutcome → _send_reply
        │         └─► no template / handoff ──► (False, meta?) → Planner / legacy path
        │
        └─► Planner / WorkflowEngine (unchanged when adaptive returns unhandled)
```

### Sequence (contributor verification, text)

```
Contributor machine (Poetry venv recommended)
        │
        ▼
poetry install
        │
        ▼
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 poetry run pytest \
    tests/test_intent_adaptive_* tests/test_i18n_locale_key_parity.py -q
        │
        ├─► green → Step 9 offline matrix satisfied for PR self-check
        └─► CI: job ``compliance-and-test`` runs the same Step 9 step plus
            ``pytest -m "not integration and not stress"`` (broader kernel gate)
```

### Degradation table (operator view)

| Trigger | What the user / next tier sees |
|--------|---------------------------------|
| ``ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED=false`` (default) | Adaptive hook returns immediately; **Planner-first** behaviour for ``COMPLEX_TASK`` (no tiered short-circuit). |
| ``ADAMI_INTENT_LLM_CLASSIFIER_ENABLED=false`` (default) | No ``call_llm`` for JSON classification; **rule tier (+ merge)** only. |
| LLM returns invalid JSON / schema | Parsed as **UNKNOWN**-style degrade with ``llm_classifier_parse_error`` (or similar) in ``reason_codes``; flow continues toward Planner / clarify per merge + registry. |
| LLM call exceeds inner timeout | ``llm_classifier_timeout``; same as above. |
| Outer ``wait_for`` on LLM phase fires (Step 8) | Falls back to **pre-LLM** classification path (tests assert no deadlock). |
| Template ``execute`` exceeds ``ADAMI_INTENT_TEMPLATE_EXECUTE_TIMEOUT_SEC`` | User copy from ``intent.adaptive.template_execute_timeout``; **no unbounded hang**. |
| ACTION template + ``ADAMI_INTENT_ACTION_TEMPLATE_REQUIRES_CONFIRMATION`` + no permission/ack | ``intent.action_template.confirm_required`` (or HITL prompt / ``hitl_fallback_body``); **execute not run**. |
| Telegram HITL path disabled or non-Telegram surface | ``intent.action_template.hitl_fallback_body`` when confirmation is still required. |
| Low confidence vs ``ADAMI_INTENT_CLASSIFIER_MIN_CONFIDENCE`` | No template win; **Planner** (optionally with Step 7 ``intent_adaptive_meta``). |
| ``route=clarify`` after merge | **Clarify** user string ``intent.clarify.prompt`` via ``_send_reply``. |

### Configuration matrix (intent-adaptive–related)

| Setting | Default | Effect (short) |
|--------|---------|----------------|
| ``ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED`` | ``false`` | Master switch for ``_maybe_route_intent_adaptive``. |
| ``ADAMI_INTENT_ADAPTIVE_FALLBACK_NOTICE`` | ``false`` | Optional one-line notice when falling through to Planner. |
| ``ADAMI_INTENT_LLM_CLASSIFIER_ENABLED`` | ``false`` | Enables JSON LLM classification after rules. |
| ``ADAMI_INTENT_CLASSIFIER_MIN_CONFIDENCE`` | ``0.55`` | Floor for template short-circuit vs Planner. |
| ``ADAMI_INTENT_CLASSIFIER_TIMEOUT_SEC`` | ``8.0`` | Inner LLM classify call timeout. |
| ``ADAMI_INTENT_ADAPTIVE_LLM_PHASE_TIMEOUT_SEC`` | ``15.0`` | Outer asyncio cap around the LLM phase (≥ inner when LLM on). |
| ``ADAMI_INTENT_TEMPLATE_EXECUTE_TIMEOUT_SEC`` | ``30.0`` | Per-template ``execute`` cap. |
| ``ADAMI_INTENT_ACTION_PERMISSION_GRANTED`` | ``false`` | When true, merge policy allows ACTION; templates may run if other gates pass. |
| ``ADAMI_INTENT_ACTION_TEMPLATE_REQUIRES_CONFIRMATION`` | ``true`` | ACTION presets need permission or per-chat ack / HITL flow. |
| ``ADAMI_INTENT_ACTION_HITL_TELEGRAM`` | ``true`` | Prefer Telegram inline confirm for ACTION when nerve is present. |
| ``ADAMI_ENABLE_HITL`` | ``false`` | Subscribes ``HitlHandler`` to ``hitl.events`` when true; ack store still works for tests. |

### CI policy (Step 9)

- **Offline:** the Step 9 pytest glob must pass **without** API keys or outbound LLM
  traffic; tests use **mocks** for ``call_llm`` / patch classifier entrypoints where needed.
- **Workflow:** ``.github/workflows/kernel-ci.yml`` (mirror: ``ci.yml``) — job
  ``compliance-and-test`` includes a named step **Intent adaptive — offline test matrix (Step 9)**
  before the full kernel pytest slice.
- **Broader gate:** the same job still runs ``poetry run pytest -m "not integration and not stress"``,
  which includes ``tests/test_decision_processor_intent_adaptive_smoke.py`` and other
  modules; optional Planner-only rows live in ``tests/test_planner_intent_adaptive_meta_step71.py``
  (may ``importorskip("aiosqlite")`` on minimal interpreters).

### Step 9 — Acceptance checklist

**S9-A. pytest (canonical offline bundle)**

```bash
poetry install
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 poetry run pytest \
  tests/test_intent_adaptive_* \
  tests/test_i18n_locale_key_parity.py \
  -q --tb=short
```

**S9-B. i18n**

- S9-B1: ``doc.intent_adaptive.ci`` is non-empty in ``en`` / ``zh-Hans`` and differs by locale.

**S9-C. Repository hygiene**

- S9-C1: ``README.md`` lists the Step 9 reviewer commands (numbered) and points to this section.
- S9-C2: CI workflow defines the Step 9 step matching **S9-A**.

## Step 10 — Cleanup and deprecation markers

**Purpose:** keep the intent-adaptive surface **release-ready**: no stray demo handlers in
bootstrap, and a clear **where to write “what changed”** story without a root ``CHANGELOG.md``.

### Built-in templates (``retrieval_echo``)

Step 6 in this repository registers **only** ``RetrievalWeatherTemplateHandler`` and
``RetrievalCryptoTemplateHandler`` via ``register_builtin_intent_templates``. A
**``retrieval_echo``** demo handler described in older internal tasklists **does not exist**
in ``cortex/intent_adaptive/templates/`` — there is nothing to delete. If contributors add a
throwaway echo (or similar) for local experiments, the module **must** begin with an English
tag comment ``# dev-only demo handler`` and must **not** be wired into
``register_builtin_intent_templates`` unless product explicitly requires it.

### Release narrative (no root changelog)

The kernel repo does **not** maintain ``CHANGELOG`` at the repository root. Use:

- **This doc** (Steps 1–10 + acceptance tables) for subsystem behaviour and defaults.
- **PR descriptions** for operator-facing deltas when changing flags, i18n keys, or safety
  gates (same pattern as the **document pipeline** notes in ``README.md``).

### Step 10 — Acceptance checklist

**S10-A. pytest**

Re-run the Step 9 offline bundle plus smoke / Planner rows when touching bootstrap or
``DecisionProcessor`` wiring:

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 poetry run pytest \
  tests/test_intent_adaptive_* \
  tests/test_i18n_locale_key_parity.py \
  tests/test_decision_processor_intent_adaptive_smoke.py \
  tests/test_planner_intent_adaptive_meta_step71.py \
  -q --tb=short
```

**S10-B. Repository hygiene**

- S10-B1: ``README.md`` includes a **Release notes** subsection stating there is no root
  ``CHANGELOG`` and pointing reviewers here for intent-adaptive release narrative.
