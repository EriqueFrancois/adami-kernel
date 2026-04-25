## 模块五：`mvanhorn/last30days-skill` 集成说明（外部 CLI 世界传感器）

### 目标与边界（必须遵守）

- **默认安装轻量**：`adami-kernel` **不**引入 `last30days-skill` 的 Python/Node 依赖，不 vendoring 其仓库作为运行时必需。
- **集成方式**：将 `last30days` 作为**外部 CLI 后端**接入。AdamI 只负责：
  - 子进程调用外部 `last30days.py`
  - 解析 stdout（`--emit=context|md|json|path`）
  - 将输出安全写入 SecondBrain（`Inbox/` 或 `Resources/`）
  - 可选：触发“消化/摘要”闭环任务（写完笔记后调度 digest）
- **安全边界**：不导入 `last30days` 的内部 runtime；不让其依赖成为 AdamI 的默认依赖。

### 外部安装 last30days（示例）

你需要在本机单独安装/获取 `last30days-skill` 仓库，并定位到 `scripts/last30days.py`。

示例（手动 clone）：

```bash
git clone https://github.com/mvanhorn/last30days-skill.git ~/ext/last30days-skill
```

脚本路径一般为：

- `~/ext/last30days-skill/scripts/last30days.py`

### 运行要求（来自官方文档）

- **Python 版本**：官方要求 **Python 3.12+**
- **CLI 关键参数**（AdamI 侧对齐的“契约”）：
  - `--emit=MODE`：`compact|json|md|context|path`
  - `--sources=MODE`：`auto|reddit|x|both`
  - `--refresh`：绕过 last30days 自身缓存
- **输出目录（last30days 自行写入）**：默认 `~/.local/share/last30days/out/`

> 注意：last30days 还可能依赖可选的第三方密钥或工具（例如 ScrapeCreators、OpenAI/xAI/OpenRouter、yt-dlp 等）。这些不属于 AdamI 默认依赖范围，按 last30days 官方文档在本机自行配置。

### 配置项（AdamI）

这些配置在 `src/adami_kernel/config.py`（默认值）与 `.env.example`（变量名提示）中已加入。

- **总开关**
  - `ADAMI_LAST30DAYS_ENABLED`：是否启用模块五（默认 `False`）
- **外部 CLI 路径与解释器**
  - `ADAMI_LAST30DAYS_SCRIPT_PATH`：外部 `last30days.py` 绝对路径
  - `ADAMI_LAST30DAYS_PYTHON`：可选，指定 Python 解释器（需 3.12+）；未指定时桥接层会探测 `python3.13/python3.12/python3`
- **执行参数**
  - `ADAMI_LAST30DAYS_EMIT_MODE`：默认 `context`（也可 `md/json/path`）
  - `ADAMI_LAST30DAYS_TIMEOUT_SEC`：单次执行超时
  - `ADAMI_LAST30DAYS_REFRESH_DEFAULT`：是否默认 `--refresh`
- **定时触发**
  - `ADAMI_LAST30DAYS_DAILY_TOPIC`：每日简报主题（不为空才触发）
  - `ADAMI_LAST30DAYS_WEEKLY_TOPIC`：每周简报主题（周一 09:00 触发）
- **落盘位置与命名**
  - `ADAMI_LAST30DAYS_WRITE_TO`：`Inbox` 或 `Resources`
  - `ADAMI_LAST30DAYS_NOTE_PREFIX`：SecondBrain 笔记文件名前缀
- **简报翻译（落盘前）**
  - `ADAMI_LAST30DAYS_TRANSLATE_DIGEST`：是否将标题与正文译为 `effective_ui_default_locale()`（默认 `True`）；还受全局 `ADAMI_TRANSLATE_ENABLED` 约束。
  - `ADAMI_LAST30DAYS_DIGEST_SOURCE_LOCALE`：假定 CLI 输出主语言（默认 `en`）；与目标 locale 相同时跳过翻译。
  - 实现位置：`.adami_data/skills/LAST30DAYS_DIGEST.py` 内调用 `translate_text_async`；LLM 走 `integration/minimal_openai_chat.py`（与完整 `HybridLLMRouter` 解耦，避免技能路径拉 MLX）。
  - 去重键 `dedupe_key` 含 UI locale 段，避免不同界面语言互相覆盖同一条笔记。
- **系统界面语言（与模块六衔接）**
  - 未设置 `ADAMI_UI_LOCALE` 时，`effective_ui_default_locale()` 使用 `ADAMI_SYSTEM_UI_LOCALE`（默认 `zh-Hans`）。`ADAMI_DEFAULT_LOCALE` 仍为 `en`（兼容/键基准，与界面默认解耦）。

### 工作流概览（实现位置）

- **外部 CLI 桥接**：`src/adami_kernel/integration/last30days_bridge.py`
  - `run_last30days(...)`：异步子进程执行、解析 `emit`、TTL cache、可选限流、结构化错误、可选 ddgs 降级
- **SecondBrain 安全写入**：
  - ingest：`src/adami_kernel/hippocampus/second_brain_ingest.py`
  - API：`src/adami_kernel/hippocampus/second_brain.py`（`write_inbox_note/write_resource_note`）
- **原生技能（可被 Planner/Executor 调用）**：`.adami_data/skills/LAST30DAYS_DIGEST.py`
  - `execute(**kwargs)`：调用 bridge → 写 SecondBrain → 返回结构化结果
- **定时触发**：`src/adami_kernel/peripheral/circadian_nerve.py`
  - 满足开关 + topic 时发布 `system.events`，指令调用 `LAST30DAYS_DIGEST`
  - 带冷却/退避避免触发风暴
- **消化闭环（可选）**：`src/adami_kernel/orchestrator/planner.py`
  - `LAST30DAYS_DIGEST` 成功后，调度 `digest this note` 任务，并写入 `StageArtifact(file://note)`

### 缓存 / 速率限制 / 降级策略（AdamI 侧）

- **TTL cache（内存）**：bridge 层按 `(topic, emit, sources, refresh)` 做缓存，避免调度层抖动重复跑外部 CLI。
- **限流（可选开关）**：bridge 支持 `enforce_rate_limit`，按 `(sources, emit)` 做最小间隔限制（适合 scheduled 路径）。
- **降级（可选开关）**：bridge 支持 `fallback_to_web_search=True` 时，用 `ddgs` 生成“最小简报”（当脚本缺失 / Python 版本不足 / 执行失败 / 超时）。

### 验收入口（推荐）

**模块五专项一键验收**（不依赖本机安装外部 `last30days.py`，使用 fake 脚本与 mock）：

```bash
poetry run pytest \
  tests/test_acceptance_module5_full_suite.py \
  tests/test_last30days_bridge.py \
  tests/test_second_brain_ingest_last30days.py \
  tests/test_skill_last30days_digest.py \
  tests/test_acceptance_module5_last30days_daily_digest.py \
  tests/test_acceptance_module5_last30days_digest_loop.py \
  -v --tb=short
```

运行非集成全仓回归（仍建议每次合并前执行）：

```bash
poetry run pytest -m "not integration"
```

本模块相关的关键测试文件：

- `tests/test_acceptance_module5_full_suite.py`（整体验收说明 + 轻量烟测）
- `tests/test_last30days_bridge.py`
- `tests/test_second_brain_ingest_last30days.py`
- `tests/test_skill_last30days_digest.py`
- `tests/test_acceptance_module5_last30days_daily_digest.py`
- `tests/test_acceptance_module5_last30days_digest_loop.py`

