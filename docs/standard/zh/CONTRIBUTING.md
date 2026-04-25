# 参与贡献 AdamI Kernel

**读者**：开源贡献者、合作方工程师。

---

## 1. 前置条件

- Python **3.10–3.13**（见 `pyproject.toml` 上界）。
- [Poetry](https://python-poetry.org/) 管理依赖。
- 可选：Docker（沙箱 / 集成测试）。

---

## 2. 开发安装

```bash
poetry install
# 可选 extras
poetry install -E training
poetry install -E mcp-agent
```

---

## 3. Git 工作流（建议）

1. **分支**：自 `main`（或组织默认分支）拉出功能分支，如 `feat/report-topic-docs`。
2. **提交**：小而可审的提交，祈使句说明（`Add DLQ metric hook`，避免 `fixed stuff`）。
3. **PR**：写清动机、风险与测试计划；关联 Issue。
4. **合并**：历史嘈杂时倾向 squash；若组织要求 merge commit 则从其规定。

仓库内**未**强制 `git-flow` 包装脚本 —— 请对齐公司内部规范。

---

## 4. 质量门禁（提交前本地应通过）

| 门禁 | 命令 |
|------|------|
| Lint | `poetry run ruff check src/ tests/` |
| 格式化（可选） | `poetry run ruff format src/ tests/` |
| 类型 | `poetry run pyright` |
| 单元测试 | `poetry run pytest -m "not integration and not stress" --tb=short` |
| i18n CJK 门禁 | `poetry run python scripts/check_no_bare_cjk_strings.py` |
| 多语言键 parity | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 poetry run pytest tests/test_i18n_locale_key_parity.py -q` |

CI 对齐见根目录 `ci.yml` / `.github/workflows/kernel-ci.yml`。

---

## 5. 测试驱动期望

- 新逻辑补充 **pytest**；昂贵用例标 `@pytest.mark.integration` 或 `@pytest.mark.stress`。
- 默认 CI 走 **快测**；回放类见 `tests/replay/`。
- 修改用户可见字符串时，须同步更新 `i18n/locales/en/common.json` 与 `zh-Hans/common.json`（见 `.cursor/rules/i18n-locale-parity.mdc`）。

---

## 6. 风格与类型

- `ruff` 行宽 **100**，语法基线 **py312**。
- `pyright` **strict** —— 新模块应无告警；若放宽忽略须在 PR 中说明理由。

---

## 7. 安全披露

若组织要求**非公开**披露严重漏洞，请勿在公开 Issue 张贴细节 —— 在维护方建立通道前，请使用 fork 私有流程或贵司安全接口。

---

## 8. 社区行为

保持明确、友善，预设善意。项目空间不容忍骚扰与歧视。
