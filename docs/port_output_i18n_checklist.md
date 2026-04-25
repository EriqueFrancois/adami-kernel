# 端口输出国际化改造清单（Step 4）

目标：用户第一眼看到的路径走 `t()` / `ui_t()` 与 `locales/*/common.json`；协议层（`callback_data` / `custom_id`）不变。

## 约定

- **DecisionProcessor**：在 `process()` 已 `attach_request_locale` 的上下文中使用 `i18n_t`（即 `adami_kernel.i18n.t`）。
- **Telegram / Discord / InteractiveShell**：无请求级 locale 时使用 `adami_kernel.i18n.ui_static.ui_t`（跟随 `settings.effective_ui_default_locale()`）。
- 长文案优先放在 `locales/en/common.json` 与 `locales/zh-Hans/common.json`，避免代码内硬编码拼接。
- **波次 0（全局）**：键前缀、占位符、`zh-Hans`/`en` 回退与「用户可见 / 日志 / 外部与显式翻译」四分法见 [`docs/i18n_boundary_and_locale_policy.md`](i18n_boundary_and_locale_policy.md)。

## 波次 1（已完成）

| 区域 | 内容 |
|------|------|
| TelegramSensory | 启动文案、设置提示、思考中、媒体不支持、入口菜单回调、digest 编辑文案、Report 向导（与 `report_wizard_i18n`）、排程提示与提交/格式错误、HITL resume 提示 |
| DiscordNerve | 同上对应路径；关闭设置按钮 label；Discord 专用 ephemeral / 频道排程提示 |
| InteractiveShell | 主菜单、选择提示、退出/中断、提示符区、无效选项、CLI 异常 |
| DecisionProcessor | `/report` 子命令用法与错误、list 标题、run 推送头与落盘提示、未知子命令、会话占用提示、任务完成与熔断用户提示 |

## 波次 2（待办，非阻塞）

- Telegram/Discord：语音/视觉/文档的 **task 内中文指令**（发往模型的 payload）与部分 **仅日志** 中文。
- DecisionProcessor：`MAINTAIN` / `WRITING` / `INTAKE` / 技能创建等大块中文回复与 `_update_ui` 状态句。
- `forbidden_phrases` 检测列表是否与多语言回复对齐。

## 回归

```bash
pytest -m "not integration"
```

Step 4 专项验收（双语键、占位符、`report:*` 协议）：`pytest tests/test_acceptance_i18n_step4_port_output.py -v`

## Step 5（Report Studio 简报）

- 正文模板：`src/adami_kernel/i18n/locales/<locale>/report.md.j2`（en / zh-Hans）；缺失时回退 **en** 文件，**catalog** 仍用请求 locale 渲染 `report.studio.*` 标题。
- 可选 SecondBrain 覆盖：`System/working-memory/report_templates/report.<locale>.md.j2`。
- 语言解析：`generate_fixed_blocks_report(..., locale=...)` → 否则 `get_request_locale()` → `settings.effective_report_locale()`（`ADAMI_REPORT_LOCALE` 未设时跟 `effective_ui_default_locale()`）。
- 验收：`pytest tests/test_acceptance_i18n_step5_report_studio.py tests/test_report_studio_template_locale.py -v`

## Step 6（显式翻译模块）

- 实现：`adami_kernel.i18n.translate`（勿从 ``adami_kernel.i18n`` 包根导入，避免与 ``config`` 循环依赖）。
- 验收：`pytest tests/test_acceptance_i18n_step6_translate.py tests/test_i18n_translate.py -v`

## Step 7（工程门禁：A 类路径裸中文）

- 脚本：`scripts/check_no_bare_cjk_strings.py`，配置：`scripts/i18n_cjk_gate.json`（`scan_globs`、`legacy_file_allowlist` 可渐进收紧）。
- CI：与 ruff 同 job 已串联；本地：`poetry run python scripts/check_no_bare_cjk_strings.py`；`ADAMI_I18N_CJK_GATE=warn` 时仅警告不失败。
- 全量候选表（默认整包 `src/adami_kernel`、仅 CJK、同门禁排除规则）：`python scripts/scan_user_visible_string_candidates.py` → `reports/user_visible_string_candidates.tsv` 与 `.md`（`reports/` 已 `.gitignore`）。
- 验收：`pytest tests/test_acceptance_i18n_step7_cjk_gate.py tests/test_i18n_cjk_gate.py -v`
