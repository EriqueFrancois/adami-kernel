# Contributing to AdamI Kernel

**Audience**: open-source contributors, partner engineers.

---

## 1. Prerequisites

- Python **3.10–3.13** (see `pyproject.toml` upper bound).
- [Poetry](https://python-poetry.org/) for dependency management.
- Optional: Docker (for sandbox / integration tests).

---

## 2. Dev install

```bash
poetry install
# optional extras
poetry install -E training
poetry install -E mcp-agent
```

---

## 3. Git workflow (recommended)

1. **Branch**: create feature branches from `main` (or your org’s default), e.g. `feat/report-topic-docs`.
2. **Commits**: small, reviewable commits with imperative messages (`Add DLQ metric hook` not `fixed stuff`).
3. **PR**: describe motivation, risk, and test plan; link issues if applicable.
4. **Merge**: prefer squash for noisy histories unless your org mandates merge commits.

There is no enforced `git-flow` wrapper in-repo — mirror your company standard.

---

## 4. Quality gates (must pass locally)

| Gate | Command |
|------|---------|
| Lint | `poetry run ruff check src/ tests/` |
| Format (optional pre-commit) | `poetry run ruff format src/ tests/` |
| Types | `poetry run pyright` |
| Unit tests | `poetry run pytest -m "not integration and not stress" --tb=short` |
| i18n CJK gate | `poetry run python scripts/check_no_bare_cjk_strings.py` |
| Locale parity | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 poetry run pytest tests/test_i18n_locale_key_parity.py -q` |

CI mirrors these steps — see root `ci.yml` / `.github/workflows/kernel-ci.yml`.

---

## 5. Test-driven expectations

- Add **pytest** coverage for new logic; mark expensive tests `@pytest.mark.integration` or `@pytest.mark.stress`.
- Prefer **fast** tests in default CI; replay suites live under `tests/replay/`.
- When touching user-visible strings, update **both** `i18n/locales/en/common.json` and `zh-Hans/common.json` (see `.cursor/rules/i18n-locale-parity.mdc`).

---

## 6. Style & typing

- `ruff` line length **100**, target **py312** syntax baseline.
- `pyright` **strict** — new modules should type-check without widening ignores unless justified in PR.

---

## 7. Security disclosures

Do **not** open public issues for undisclosed critical vulnerabilities if your policy requires private disclosure — contact maintainers per `SECURITY.md` guidance once a channel exists; until then, use your fork’s private process.

---

## 8. Community conduct

Be explicit, kind, and assume good intent. Harassment or bigotry is not tolerated in project spaces.
