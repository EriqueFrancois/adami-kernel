# Skill module acceptance audit (2026-04)

This document is the single source of truth (SSOT) for the end-to-end **skill** pipeline audit, fixes applied in-repo, and how to verify them. UI / wizard one-liners: i18n key **`doc.skill.pipeline`** in `locales/en/common.json` and `locales/zh-Hans/common.json`.

---

## 中文摘要

- **技能主链路**：意图与路由 → 代码生成/清洗（`SkillFactory` / `SkillWasher`）→ 工程化与校验（`SkillBuilder` / `SkillValidator`）→ 运行时质检（`SkillInspector`）→ 落盘与注册（`EvolutionEngine` / `SkillManager`）→ 可选向量索引（`VectorStore`）。
- **启动计数**：Web/统计使用的 `SkillLoader` 位于 **`adami_kernel.nexus.skill_loader`**，从 **Evolution 内存** 同步；**不是** `skill_manager/skill_loader.py`（后者为历史备用实现，已在模块 docstring 标明）。
- **已修复问题**：见下文 *Issues found & resolved*；**PolicyLoader** 在 manifest 未变化时不再每分钟打 INFO「热更新」日志（见 *Policy hot reload*）。
- **残留风险**：`SkillManager` 仅在 `dream_sandbox` 与 `router` 同时存在时初始化；若沙箱未就绪，`skill_manager` 可能为 `None`，调用方需判空（见 *Residual risks*）。
- **二次全目录审计**：已遍历 `skill_manager/` 下全部 27 个 `.py` 的职责表（见下 inventory）；并修复 `SkillCleaner` / `VectorStore` / `SkillInspector` / 遗留 `skill_loader` 等问题（见 *Second pass*）。

---

## Architecture (reference)

```text
User / Planner / SkillRouter
        │
        ▼
SkillFactory ──► SkillWasher (GitHub tier)
        │
        ▼
SkillBuilder ──► SkillValidator (static + optional validate_async / DreamSandbox)
        │
        ▼
SkillInspector (name / AST / security / runtime)
        │
        ▼
EvolutionEngine.create_new_skill
        │
        ▼
SkillManager.inspect_and_register ──► LayeredMemory + VectorStore
```

File discovery highlights:

| Role | Primary module |
|------|----------------|
| Disk load + AST gate | `skill_manager/skill_file_loader.py` (used by Evolution) |
| Boot skill count sync | `nexus/skill_loader.py` |
| Legacy file loader | `skill_manager/skill_loader.py` (not wired in default boot) |

### `skill_manager/` package inventory (every module under this directory)

| Module | Role |
|--------|------|
| `__init__.py` | Public exports |
| `anthropic_skill_importer.py` | Anthropic `SKILL.md` → `SkillMetadata` |
| `code_normalizer.py` | AST / formatting normalization |
| `code_quality_scorer.py` | Quality scoring for optimizer |
| `skill_builder.py` | Wrap, write disk, `SkillValidator.validate_async` |
| `skill_cleaner.py` | Idle / orphan / pollution cleanup |
| `skill_code_generator.py` | LLM code generation |
| `skill_debug.py` | Persist failed skill snippets |
| `skill_factory.py` | Multi-backend code generation + TDD hook |
| `skill_file_loader.py` | Load `.py` from disk into Evolution (production path) |
| `skill_inspector.py` | Pre-register QA (AST, security, sandbox/host runtime) |
| `skill_loader.py` | **Legacy** file loader (not default boot); see module docstring |
| `skill_lifecycle.py` | In-memory lifecycle states |
| `skill_manager.py` | Register orchestration, metadata, vector sync |
| `skill_metadata.py` | Pydantic models |
| `skill_optimizer.py` | Optimization loop |
| `skill_router.py` | Intent + routing |
| `skill_template.py` / `skill_template_repository.py` | Static templates |
| `skill_tdd_generator.py` | TDD case generation |
| `skill_usage_manager.py` | usage.json + instinct threshold |
| `skill_validator.py` | Static + optional async sandbox validation |
| `skill_validation_result.py` | Validation DTO |
| `skill_version_manager.py` | Versions, instinct/protected flags |
| `temp_skill_workspace.py` | Temp file staging |
| `vector_store.py` | Chroma skill index |

---

## Policy hot reload (AdamI-PolicyLoader)

**Previous behavior:** `PolicyLoader.poll_reload()` sleeps `ADAMI_POLICY_RELOAD_INTERVAL_SEC` (default **60**), then calls `reload_safe()`. `reload_safe()` always logged **INFO** `boot.log.policy_manifest_hot_reload` whenever a previous manifest existed—even if the JSON was **unchanged**. That produced one line per minute (e.g. `version=0.1.0`).

**Verdict:** The interval is **by design**; the **per-minute INFO line for an unchanged file** was noisy and misleading (it implied a real reload every time).

**Fix:** If `prev.model_dump() == manifest.model_dump()`, return early **without** assigning or logging. Real edits still emit `boot.log.policy_manifest_hot_reload`.

**Tests:** `tests/test_policy_loader_reload_idempotent.py`

---

## Issues found & resolved (this pass)

### Cross-cutting / earlier fixes (still valid)

1. **PolicyLoader spam** — Unchanged manifest no longer triggers INFO hot-reload logs (`policy/loader.py`).
2. **SkillManager Anthropic cache key mismatch** — `_anthropic_cache` keys unified to **`skill_name.upper()`** in `get_skill_metadata` (`skill_manager.py`).
3. **`skill_loader.py` Anthropic path** — Replaced invalid `meta.name` with **`skill_name`**; module marked legacy (`skill_loader.py`).
4. **SkillFileLoader duplicate-instinct skip** — Checks both lower/upper `.py` on disk (`skill_file_loader.py`).

### Second pass — full `skill_manager/` directory audit (2026-04-12)

5. **SkillCleaner wrong “latest” metadata** — `_load_metadata` used “first wins”, but `LayeredMemory.retrieve_recent` returns rows in **chronological order (oldest → newest)**. That kept the **oldest** row per `skill_name`, so idle/orphan rules could run on stale status/metrics. **Fixed:** last row wins per skill (`skill_cleaner.py`). **Test:** `tests/test_skill_cleaner_latest_metadata.py`.
6. **SkillCleaner file deletion case** — `_delete_skill` only tried `{name}.py` lowercased; Evolution may write **uppercase** filenames. **Fixed:** try both cases in skills and instincts dirs (`skill_cleaner.py`).
7. **SkillInspector bare `except`** — JSON parse and AST parse used bare `except`. **Fixed:** narrow exception types (`skill_inspector.py`).
8. **VectorStore bad-skill cleanup + rebuild keys** — `_cleanup_bad_skills` could hit duplicate `skill_name` rows in any order; **dedupe by skill_name** (last wins). **`rebuild_index`** normalizes keys with **`.upper()`** for stable Chroma ids. **`add_skill` / `remove_skill`** normalize `skill_name` to upper (`vector_store.py`).
9. **`skill_loader.cleanup_corrupted_skills`** — Previously deleted **all** `.py` under **both** dynamic and instinct trees (catastrophic if called). **Fixed:** only scans **`skills_dir`**; instincts are never touched; docstring warns to use `SkillFileLoader` via Evolution (`skill_loader.py`).

---

## Residual risks & recommendations

| Risk | Mitigation |
|------|------------|
| `SkillManager` is `None` when `dream_sandbox` or `router` is falsy | Call sites should use `if skill_manager:` before `inspect_and_register`. Consider a no-op stub in a future refactor. |
| `ADAMI_SKIP_DOCKER_SANDBOX` default `True` on hosts | In-container auto **`ADAMI_RUNTIME_PROFILE=production`** sets **`ADAMI_SKIP_DOCKER_SANDBOX=false`** unless overridden; DreamSandbox uses **`ADAMI_DOCKER_SANDBOX_*`** hardening. |
| Two classes named `SkillLoader` | Prefer imports from `nexus.skill_loader` for boot paths; see README. |
| Legacy `skill_loader.cleanup_corrupted_skills` | Now **skills_dir only** (no instinct wipe). Prefer `SkillFileLoader.cleanup_corrupted_skills` via `EvolutionEngine`. |

---

## Configuration reference

| Variable | Purpose |
|----------|---------|
| `ADAMI_SKILL_VALIDATOR_SANDBOX_ENABLED` | Enable post-static sandbox import check in `SkillValidator.validate_async` |
| `ADAMI_SKILL_VALIDATOR_SANDBOX_TIMEOUT_SEC` | Timeout for sandbox command |
| `ADAMI_SKIP_DOCKER_SANDBOX` | Prefer host-mode execution paths where supported (`production` profile forces Docker path unless overridden) |
| `ADAMI_RUNTIME_PROFILE` | `development` \| `production`; unset = auto from `/.dockerenv` |
| `ADAMI_DOCKER_SANDBOX_READ_ONLY_ROOTFS` | DreamSandbox: read-only root + tmpfs `/tmp` |
| `ADAMI_DOCKER_SANDBOX_DROP_ALL_CAPABILITIES` | DreamSandbox: `cap_drop: ALL` |
| `ADAMI_DOCKER_SANDBOX_NO_NEW_PRIVILEGES` | DreamSandbox: `security_opt: no-new-privileges:true` |
| `ADAMI_POLICY_RELOAD_INTERVAL_SEC` | Policy manifest poll interval (seconds) |

---

## Verification commands

**Skill package + Tier3 / 磁盘技能 / 策略轮询（推荐每次发版前跑）：**

```bash
poetry run pytest \
  tests/test_skill_package_health.py \
  tests/test_skill_cleaner_latest_metadata.py \
  tests/test_skill_manager_anthropic_cache.py \
  tests/test_search_similar_skill.py \
  tests/test_skill_last30days_digest.py \
  tests/test_policy_loader_reload_idempotent.py \
  -q
```

**Skill / market / web 相关 i18n 键（Wave3）：**

```bash
poetry run pytest tests/test_acceptance_i18n_wave3_skill_market_web.py -q
```

其他广谱测试（按需，全量可能受环境/网络影响）：

```bash
poetry run pytest tests/ -q --tb=no -k "skill"   # 名称含 skill 的子集
```

---

## Sign-off checklist

- [x] PolicyLoader: no INFO log on idempotent `reload_safe`
- [x] SkillManager: Anthropic cache key case alignment + regression test
- [x] SkillCleaner: latest metadata per skill + regression test
- [x] SkillCleaner / VectorStore: case-normalized paths / ids where applicable
- [x] SkillInspector: no bare `except` in audited paths
- [x] Legacy `skill_loader`: safe cleanup scope + Anthropic `skill_name` fix
- [x] Skill pipeline documented in README + `doc.skill.pipeline` (en / zh-Hans)

**Auditor:** automated + codebase review (Cursor agent), 2026-04-12 (updated: full `skill_manager/` tree pass).
