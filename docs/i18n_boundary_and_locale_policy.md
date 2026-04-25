# Module 6 — Internationalization (i18n) Boundary & Locale Policy (Step 0)

**中文摘要**：本文定义「用户可见 / 日志与诊断 / 外部内容与显式翻译管道」三类边界；波次 0 起固定 **catalog 键前缀**、**占位符**与 **zh-Hans ↔ en 回退** 的工程约定，并与 `config.py` 中的 `ADAMI_SYSTEM_UI_LOCALE` / `ADAMI_DEFAULT_LOCALE` 及 Report Studio 模板策略对齐。

This document freezes the engineering boundary for **Module 6: Multi-language support**.
Goal: prevent an “translate everything” project, keep incident response reliable, and keep user-visible UX consistent across **CLI / Telegram / Discord** (and aligned with **Report Studio**).

---

## 1) Text classes (must be classified before coding)

### A — User-visible UI (must be i18n / catalog)

Strings that a human operator/user is expected to read as part of product behavior:

- Entry menus, wizards, button labels (human-readable `text` / `label`)
- Command help (`/report help`, wizard prompts)
- User-facing error summaries shown in chat/CLI (not stack traces)

**Rule:** no hard-coded user-facing sentences in business logic long-term; use **stable dotted keys** + **`locales/<locale>/common.json`** (or SecondBrain overrides), resolved via **`t()` / `ui_t()` / `i18n_t()`** as described in `docs/port_output_i18n_checklist.md`.

**Anti-pattern:** building sentences by concatenating literals with variables (`"错误：" + msg`). Use **one catalog string** with **named placeholders** (see §7).

### B — System logs / audit / diagnostics (English-first, not user-locale)

Machine-oriented outputs where language switching hurts operations:

- File logs (e.g. `.adami_data/kernel.log`), structured audit lines
- Trace fields, internal exceptions, debug dumps
- Developer-oriented `logger.*` messages

**Rule:** **do not bind log language to UI locale**. Keep logs English-first (or language-neutral identifiers + English), stable tokens, searchable.

### C — User-generated / external content (pass-through by default)

Content not authored by AdamI as UI:

- User prompts, pasted documents, retrieved web pages
- SecondBrain notes authored by users
- Tool outputs from third parties unless explicitly requested

**Rule:** default is **pass-through**.

### D — Explicit translation pipeline (optional, not “catalog i18n”)

Long or non-template text that product **chooses** to translate at runtime (e.g. external CLI digest body) uses **`adami_kernel.i18n.translate.translate_text_async`**, with **caching, timeout, audit**, and **must remain opt-in per call site** — not a substitute for class **A** keys.

**Rule:** do not silently translate class **C** content; class **D** is **explicit** in code and configuration (`ADAMI_TRANSLATE_*`, feature flags).

---

## 2) Locale identifiers (BCP 47) & runtime defaults

- **Supported packs (today):** `en`, `zh-Hans` (see `ADAMI_SUPPORTED_LOCALES` in `config.py`).
- **Reserved Chinese pack:** `zh-Hans` (preferred).  
  - `zh_CN` may appear historically in OS/env; treat it as an **alias** mapped to `zh-Hans` at the normalization layer (`adami_kernel.i18n.locale_utils.normalize_locale`).
- **Future languages:** must be valid BCP 47 tags (examples: `ja`, `ko`, `fr`, `de`).

### Runtime UI default (sync with `config.py`)

- **`ADAMI_DEFAULT_LOCALE`** remains **`en`**: compatibility anchor and validator default; **not** the same thing as “first screen language”.
- **Unset `ADAMI_UI_LOCALE`:** UI / static menus follow **`ADAMI_SYSTEM_UI_LOCALE`** (default **`zh-Hans`**).
- **Explicit `ADAMI_UI_LOCALE`:** overrides both for wizard/static UI resolution (`settings.effective_ui_default_locale()`).

### Normalization rules (engineering contract)

1. Trim whitespace, replace `_` with `-`, lowercase the language subtag segment where applicable.
2. Map known aliases:
   - `zh-CN`, `zh_CN`, `zh-cn` → `zh-Hans` (unless a future rule introduces `zh-Hant`)
3. Unknown/unsupported locale → fallback per `Settings` validators (see `normalize_i18n_locale_settings`).

---

## 3) Non-goals (explicitly out of scope for Module 6)

- Translating **all** code comments across the repository (low user value, high merge conflict cost)
- Translating logs to match each user’s language
- “Always-on” machine translation for all tool outputs (cost + instability)

---

## 4) Acceptance criteria for Step 0 (review gate)

- Any new Module 6 change must declare whether touched strings are **A / B / C / D**.
- **Class A** work must land keys in **`locales/en/common.json` and `locales/zh-Hans/common.json`** (parity target for the two shipped packs).
- **Class B** remains English-first; no coupling to `effective_ui_default_locale()`.
- **Class D** (optional translation) must be **explicit**, cache-aware, timeout-bound, and must not affect class **B** outputs.

---

## 5) Ownership

Product/engineering owns this boundary. If a string is ambiguous, default to **B** (logs) unless it is clearly shown to an end user as UI.

---

## 6) Wave 0 — Catalog key naming (module prefixes)

All **class A** keys are **flat dotted strings** in `common.json`. Use **lower_snake** segments; avoid embedding locale or platform in the key.

| Prefix | Owning area (guidance) | Examples (patterns) |
|--------|-------------------------|---------------------|
| `report.*` | Report Studio, `/report` UX, wizard copy | `report.help.body`, `report.wizard.prompt.timezone` |
| `settings.*` | CLI / chat settings wizard, field prompts | `settings.menu.entry`, `settings.field_prompt.instruction` |
| `port.*` | Telegram / Discord / shell **port output** (boot, callbacks, media errors) | `port.boot.system_ready`, `port.media.unsupported` |
| `dp.*` | **DecisionProcessor** user-visible replies not covered by `report.*` / `port.*` | (introduce as strings migrate) |
| `nexus.*` | **nexus/** shared nerves, bus, registry — when not better placed under `port.*` | (sparingly; prefer `port.*` for channel UX) |
| `planner.*` | **TaskPlanner** / orchestration user-visible short messages | (introduce as strings migrate) |
| `errors.*` | Shared user-facing errors | `errors.report.json_invalid` |

**Rules:**

1. Prefer **existing** prefixes (`report.*`, `settings.*`, `port.*`, `errors.*`) before inventing a new top-level bucket.
2. New bulk migrations may add **`dp.*`**, **`planner.*`**, **`nexus.*`** as needed; keep names **stable** (keys are API).
3. Stable identifiers for Python code live in **`src/adami_kernel/i18n/keys.py`** where practical (`UI`, `Report`, …); ad-hoc keys are allowed but should be rare.

---

## 7) Wave 0 — Placeholders & formatting (no raw concatenation)

- Catalog values use **Python `str.format`** semantics via `Translator.t(..., **kwargs)` (see `catalog.py`).
- **Named placeholders only:** `{detail}`, `{ctype}`, `{idx}` — **never** positional `{}` or `%s` in JSON values.
- **Every** placeholder appearing in the **chosen** catalog string (after locale fallback) must be supplied at call time; otherwise `ValueError` is raised (fail fast).
- **Do not** concatenate user-visible fragments in Python; one sentence → one key (or compose from **fully translated** clauses using placeholders if product copy allows).

---

## 8) Wave 0 — Missing-language fallback (catalog vs Report templates)

### Catalog (`common.json`) — `Translator`

Resolution order for a key is implemented in **`adami_kernel/i18n/catalog.py`**:

1. Requested locale (e.g. `zh-Hans`)
2. Then **`en`**
3. If still missing: return the **key string** (and optional dev warning)

So for the two shipped packs: **always author `en` + `zh-Hans`** for class **A** keys; other locales may reuse `en` until translated.

### Report Studio Jinja body (`report.md.j2`)

Aligned with `docs/port_output_i18n_checklist.md` (Step 5):

- Template files live under `src/adami_kernel/i18n/locales/<locale>/report.md.j2`.
- If a locale file is **missing**, the renderer falls back to the **`en`** template file for the body, while **catalog** titles (`report.studio.*`) still follow the **effective report locale** chain.

**Conceptual alignment:** both stacks use **`en` as structural fallback**; **zh-Hans** is the co-primary pack for UI today.

---

## 9) Wave 0 — Tooling cross-reference

- Port-output checklist: `docs/port_output_i18n_checklist.md`
- Candidate list (AST, excludes docstrings / common logging / `re` pattern first arg):  
  `python scripts/scan_user_visible_string_candidates.py`
- CI CJK gate (progressive): `scripts/check_no_bare_cjk_strings.py` + `scripts/i18n_cjk_gate.json`

---

## 10) Revision history (high level)

- **Wave 0:** module key prefixes, placeholder rules, catalog vs Report fallback wording, classes **A–D** (split explicit translation **D** from pass-through **C**), runtime UI defaults aligned with `ADAMI_SYSTEM_UI_LOCALE`.
