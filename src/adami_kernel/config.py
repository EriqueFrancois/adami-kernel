# src/adami_kernel/config.py
# 文件路径：src/adami_kernel/config.py
#
# 配置约定（重要）
# ----------------
# • .env：只放**密钥、令牌、密码**等不能明文进仓库的项（见仓库根目录 .env.example）。
# • 本文件：所有**可手动调整的非敏感项**（路径、开关、端口、定时训练钟点等）以**类内默认值**为准；
#   需要改行为时，请直接修改下方对应字段，而不是写进 .env。
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, List, Literal, Optional, cast

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("AdamI-Config")

# ``check_api_keys`` 可能在同一进程内被触发多次（例如 Pydantic 多轮校验）；每个密钥名只打一次
# 占位符警告，避免 CLI 启动时刷屏。``reload_settings()`` 会清空集合以便向导改配后再次提示。
_PLACEHOLDER_SAFETY_WARNED: set[str] = set()

# CLI 向导写入的 env 片段：默认 ``{ADAMI_DATA_DIR}/cli_overrides.env``（当进程环境已导出
# ADAMI_DATA_DIR 时）；否则保持历史相对路径 ``.adami_data/cli_overrides.env``（与旧版兼容）。
# 可用 ADAMI_CLI_ENV_FILE 显式覆盖读写路径。
_DEFAULT_CLI_OVERRIDES_RELATIVE_LEGACY = ".adami_data/cli_overrides.env"


def cli_overrides_env_path() -> Path:
    """与 Settings 第二路 env_file 对齐的路径，供 CLI 向导读写。"""
    explicit = os.environ.get("ADAMI_CLI_ENV_FILE")
    if explicit and str(explicit).strip():
        return Path(str(explicit).strip()).expanduser()
    data_dir = os.environ.get("ADAMI_DATA_DIR")
    if data_dir and str(data_dir).strip():
        return Path(str(data_dir).strip()).expanduser() / "cli_overrides.env"
    return Path(_DEFAULT_CLI_OVERRIDES_RELATIVE_LEGACY).expanduser()


def _settings_env_files() -> tuple[str, ...]:
    return (".env", str(cli_overrides_env_path()))


class Settings(BaseSettings):
    """AdamI 统一配置中心。

    - 业务默认值：本类字段（修改后全项目生效）。
    - .env：仅用于注入密钥类敏感项；pydantic-settings 仍会读取 .env，但非敏感项请放在本文件。
    - ``cli_overrides.env``（见 ``cli_overrides_env_path()``）：CLI「config」向导写入，加载顺序晚于 .env。
    """

    model_config = SettingsConfigDict(
        env_file=_settings_env_files(),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ====================== 通用配置 ======================
    DEBUG: bool = False
    # First-run initialization gate. When False, `adami` will prompt a minimal initializer and refuse to boot.
    ADAMI_FIRST_RUN_COMPLETE: bool = False
    # Commercial onboarding: if True, allow running without Telegram/Discord by acknowledging CLI-only mode.
    ADAMI_CLI_ONLY_MODE: bool = False
    ADAMI_DATA_DIR: str = ".adami_data"
    # Per-chat CLI/Telegram/Discord 任务队列 JSON（持久化）；路径默认 ``{ADAMI_DATA_DIR}/task_queue.json``。
    ADAMI_TASK_QUEUE_PATH: Optional[str] = None
    # 待处理队列项 ``created_at`` 超过该秒数则丢弃；``0`` 表示不启用 TTL。
    ADAMI_TASK_QUEUE_TTL_SEC: float = 3600.0
    # 后台扫描过期队列的间隔（秒）；``0`` 表示不启动扫描（仍会在 load/enqueue/save 时清扫）。
    ADAMI_TASK_QUEUE_SWEEP_SEC: float = 60.0
    # 启动后是否向 Telegram/Discord 推送「上次未完成队列」按钮（无用户输入时的主动消息）。
    ADAMI_TASK_QUEUE_NOTIFY_ON_BOOT: bool = False
    # 启动后是否向默认 chat 推送「已正常启动」；False 时仅在用户发消息后补发入口（避免 watchdog 重启刷屏）。
    ADAMI_MESSENGER_NOTIFY_BOOT: bool = False
    # Telegram polling 启动时丢弃停机期间积压的 getUpdates（避免重启后把旧消息当新请求处理）。
    ADAMI_TELEGRAM_DROP_PENDING_UPDATES: bool = True
    # 运行中任务 ``started_at`` 超过该秒数则视为过期（用于崩溃/重启恢复的自愈）；``0`` 表示不启用。
    ADAMI_TASK_QUEUE_IN_PROGRESS_TTL_SEC: float = 900.0
    # 单 chat 最大待处理条数；超出时丢弃**最旧**待处理项以接纳新任务；``0`` 表示不限制。
    ADAMI_TASK_QUEUE_MAX_PER_CHAT: int = 200
    # 全实例待处理条数上限（所有 chat 之和）；超出时从最「长」队列头部丢弃；``0`` 表示不限制。
    ADAMI_TASK_QUEUE_MAX_TOTAL: int = 5000
    # ``drop_oldest``：超限时丢弃最旧待处理；``reject``：超限则不入队（用户侧见 ``dp.session.queue_capped``）。
    ADAMI_TASK_QUEUE_OVERFLOW_MODE: Literal["drop_oldest", "reject"] = "drop_oldest"
    # 可选：Fernet URL-safe base64 密钥（与 ``cryptography.fernet.Fernet`` 兼容）；设置后磁盘文件为加密封装。
    ADAMI_TASK_QUEUE_FERNET_KEY: Optional[str] = None

    # ====================== DLQ（Dead Letter Queue） ======================
    # 启动时清空一次 DLQ（用于从旧版本/错误配置中恢复，避免 DLQ 重放刷屏）。
    # 注意：默认关闭，避免在你依赖 DLQ 恢复能力时误删待重放事件。
    ADAMI_DLQ_CLEAR_ON_BOOT: bool = False

    # ====================== i18n（模块六）语言偏好 ======================
    # 兼容/键基准：保持 ``en``（与「界面默认简体」解耦；向导文案仍可能引用此字段）。
    ADAMI_DEFAULT_LOCALE: str = "en"
    # 未设置 ``ADAMI_UI_LOCALE`` 时，界面 / Report 默认语言（系统级简体预设）。
    ADAMI_SYSTEM_UI_LOCALE: str = "zh-Hans"
    # 显式覆盖界面/向导（cli_overrides）；未设置则跟随 ``ADAMI_SYSTEM_UI_LOCALE``。
    ADAMI_UI_LOCALE: Optional[str] = None
    # Report Studio 简报正文模板与固定标题语言；未设置时跟随 effective_ui_default_locale()。
    ADAMI_REPORT_LOCALE: Optional[str] = None
    ADAMI_SUPPORTED_LOCALES: List[str] = ["en", "zh-Hans"]
    ADAMI_BRAIN_LOCALE_JSON_RELATIVE: str = "System/working-memory/locale.json"
    # 步骤 6：显式 ``translate_text_async``；关闭则始终回传原文（不调 LLM）。
    ADAMI_TRANSLATE_ENABLED: bool = True
    ADAMI_TRANSLATE_TIMEOUT_SEC: float = 30.0
    ADAMI_TRANSLATE_MAX_CHARS: int = 50_000
    ADAMI_TRANSLATE_CACHE_TTL_SEC: float = 604800.0
    ADAMI_TRANSLATE_CACHE_DIR: Optional[str] = None

    # ====================== Document → Markdown (Step 6: ops / observability) ======================
    # ADAMI_MARKITDOWN_ENABLED:
    #   None = auto — run the MarkItDown attempt only when ``importlib.util.find_spec("markitdown")`` succeeds.
    #   False = kill-switch — skip MarkItDown entirely (``multi_modal`` goes straight to unstructured / missing extractors).
    #   True (default) = always attempt the MarkItDown path first for whitelisted suffixes (still returns NOT_INSTALLED if the extra is absent).
    ADAMI_MARKITDOWN_ENABLED: Optional[bool] = True
    # Shared timeout budget for MarkItDown convert and unstructured ``partition`` on the same on-disk file path.
    ADAMI_DOCUMENT_MARKDOWN_TIMEOUT_SEC: float = 45.0
    # Reject path-based inputs larger than this before invoking MarkItDown (``convert_document_path_to_markdown``).
    ADAMI_DOCUMENT_MARKDOWN_MAX_INPUT_BYTES: int = 50 * 1024 * 1024
    # Design-output policy (awesome-design-systems discipline): prepended only when ``call_llm(..., apply_design_output_policy=True)`` (chat + Report Studio).
    ADAMI_DESIGN_OUTPUT_POLICY_ENABLED: bool = True
    # Optional override path (absolute or relative to repo root); default ``docs/design_output_policy.md``.
    ADAMI_DESIGN_OUTPUT_POLICY_PATH: Optional[str] = None
    # When True and ``PromptBuilder`` has ``second_brain``, append one i18n line to action prompts: prefer
    # on-disk SecondBrain notes (``retrieve_brain_snippets`` scopes) before ad-hoc retrieval. Default True.
    ADAMI_PROMPT_KNOWLEDGE_WIKI_HINT: bool = True
    # When True and ``PromptBuilder`` has ``second_brain``, append ``doc.pipeline.output_examples_report`` (Report Studio
    # → SecondBrain SSOT one-liner). Default True.
    ADAMI_PROMPT_OUTPUT_EXAMPLES_REPORT_HINT: bool = True

    # ====================== Intent adaptive — LLM classifier (Step 4) ======================
    # When ``ADAMI_INTENT_LLM_CLASSIFIER_ENABLED`` is True, ``maybe_llm_classify_after_rule``
    # may call ``HybridLLMRouter.call_llm`` for ``COMPLEX_TASK`` rows where the rule tier is
    # missing, ``UNKNOWN`` family, or ``confidence < ADAMI_INTENT_CLASSIFIER_MIN_CONFIDENCE``.
    # When False, callers keep Step-3-only ``rule_classify_after_router`` behaviour.
    ADAMI_INTENT_LLM_CLASSIFIER_ENABLED: bool = False
    ADAMI_INTENT_CLASSIFIER_MIN_CONFIDENCE: float = 0.55
    ADAMI_INTENT_CLASSIFIER_TIMEOUT_SEC: float = 8.0
    # When True, ``action`` may remain primary in multi-label merge (Step 4.1); default False demotes.
    ADAMI_INTENT_ACTION_PERMISSION_GRANTED: bool = False
    # Step 5: when True, ``DecisionProcessor`` runs the tiered intent pipeline (rules → optional LLM →
    # ``intent_template_registry``) before ``TaskPlanner`` on ``COMPLEX_TASK``. Default False preserves
    # legacy behaviour (Planner-only for complex tasks).
    ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED: bool = False
    # When True with the pipeline enabled, send ``intent.adaptive.user.fallback_to_planner`` once before
    # delegating to the Planner after a non-terminal adaptive outcome (opt-in UX).
    ADAMI_INTENT_ADAPTIVE_FALLBACK_NOTICE: bool = False
    # --- Step 8 (intent adaptive): timeouts, ACTION template gate, production guards ---
    # Outer ``asyncio.wait_for`` around ``maybe_llm_classify_with_settings`` in ``DecisionProcessor``.
    # Should be ≥ ``ADAMI_INTENT_CLASSIFIER_TIMEOUT_SEC`` when the LLM classifier is enabled.
    ADAMI_INTENT_ADAPTIVE_LLM_PHASE_TIMEOUT_SEC: float = 15.0
    # Per-template ``IntentTemplateHandler.execute`` budget (web + optional LLM inside handler).
    ADAMI_INTENT_TEMPLATE_EXECUTE_TIMEOUT_SEC: float = 30.0
    # When True (default), ``IntentFamily.ACTION`` cannot auto-run a winning preset template unless
    # ``ADAMI_INTENT_ACTION_PERMISSION_GRANTED`` is True or ``router_data`` is a dict with
    # ``intent_action_user_ack=True`` (host/UI explicit confirmation).
    ADAMI_INTENT_ACTION_TEMPLATE_REQUIRES_CONFIRMATION: bool = True
    # When True (default), Telegram may show inline confirm/abort for ACTION templates (Step 8.1 HITL).
    ADAMI_INTENT_ACTION_HITL_TELEGRAM: bool = True

    # ====================== 健康检查 / Web Console bind ======================
    # Loopback-only by default. Public access belongs behind Nginx/SSH tunnel, not 0.0.0.0.
    ADAMI_HEALTH_PORT: int = 8080
    ADAMI_HEALTH_BIND_HOST: str = "127.0.0.1"
    ADAMI_WEB_BIND_HOST: str = "127.0.0.1"

    # ====================== 【第三阶段核心】技能生成后端选择 ======================
    ADAMI_SKILL_BACKEND: str = "github"

    # ====================== 【GitHubHunter 配置】新增最低星级设置 ======================
    ADAMI_GITHUB_MIN_STARS: int = 3000

    # ====================== 技能相关 ======================
    ADAMI_SKILL_TIMEOUT: int = 60
    # SkillValidator：静态校验通过后是否在 DreamSandbox 内做 import 级试跑（需 Docker 或未跳过沙箱）。
    ADAMI_SKILL_VALIDATOR_SANDBOX_ENABLED: bool = True
    ADAMI_SKILL_VALIDATOR_SANDBOX_TIMEOUT_SEC: float = 45.0
    ADAMI_WORKFLOW_LLM_NODE_TIMEOUT: int = 300
    ADAMI_WORKFLOW_SKILL_BUILD_TIMEOUT: int = 300
    ADAMI_USAGE_THRESHOLD: int = 3

    # ====================== 资源阈值 ======================
    ADAMI_CRITICAL_CPU_PERCENT: float = 85.0
    ADAMI_CRITICAL_RAM_PERCENT: float = 90.0
    ADAMI_CPU_DANGER_TICKS: int = 3

    # ====================== LLM API Keys ======================
    KIMI_API_KEY: Optional[str] = None
    QWEN_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    GLM_API_KEY: Optional[str] = None
    GEMINI_API_KEY: Optional[str] = None
    GROK_API_KEY: Optional[str] = None
    GROQ_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    DEEPSEEK_API_KEY: Optional[str] = None
    MINIMAX_API_KEY: Optional[str] = None
    LLM_API_KEY: Optional[str] = None

    # ====================== 本地 LLM (Hybrid) ======================
    OLLAMA_ENABLED: bool = True
    OLLAMA_MODEL: str = "qwen3.5:9b"
    OLLAMA_HOST: str = "http://localhost:11434"

    # MLX can hard-crash (abort) at import time in some environments. Keep it opt-in.
    ADAMI_MLX_ENABLED: bool = False
    ADAMI_MLX_MODEL_PATH: str = "mlx-community/Qwen3.5-9B-MLX-4bit"
    ADAMI_MLX_MAX_TOKENS: int = 2048
    ADAMI_MLX_TEMPERATURE: float = 0.3

    # ====================== DP / 事件追踪（诊断用） ======================
    # When enabled, DecisionProcessor + LifecycleManager emit per-event debug logs:
    # event receipt, session-turn acquisition outcome, and reply dedupe decisions.
    ADAMI_DP_EVENT_DEBUG: bool = False

    # ====================== GraphMemory（SQLite 图谱） ======================
    # 默认 ``{ADAMI_DATA_DIR}/graph_memory.db``；可由此项覆盖路径。
    ADAMI_GRAPH_MEMORY_SQLITE_PATH: Optional[str] = None

    # ====================== 外围接入 ======================
    TELEGRAM_CHAT_ID: Optional[int] = None
    TELEGRAM_BOT_TOKEN: Optional[str] = None
    DISCORD_BOT_TOKEN: Optional[str] = None
    DISCORD_DEFAULT_CHANNEL_ID: Optional[str] = None
    DISCORD_DEFAULT_GUILD_ID: Optional[str] = None
    # Slash commands: default is global sync (DM + all guilds). Set this only for dev “instant guild” sync.
    DISCORD_SLASH_GUILD_ID: Optional[str] = None
    DISCORD_DEFAULT_USER_ID: Optional[str] = None
    GITHUB_TOKEN: Optional[str] = None

    # ====================== LLM 模型选择 ======================
    ADAMI_FAST_MODEL: str = "deepseek-chat"
    ADAMI_THINK_MODEL: str = "gemini-2.0-flash-thinking-exp-1219"
    ADAMI_SUBCONSCIOUS_MODEL: str = "gemini-3.1-flash"
    LLM_BASE_URL: str = "https://api.openai.com/v1"

    # ====================== 【2.0 阶段特性开关】 ======================
    ADAMI_USE_WORKFLOW_ENGINE: bool = True
    ADAMI_SKILL_CREATION_USE_WORKFLOW_ENGINE: bool = True
    ADAMI_USE_MULTI_AGENT: bool = True
    ADAMI_USE_REFLEXION_LOOP: bool = True
    ADAMI_USE_TDD_EVOLUTION: bool = True

    # Tracing on by default; span export defaults to **Console** (no Collector). Set ``ADAMI_OTEL_EXPORTER=otlp`` for gRPC.
    ADAMI_ENABLE_OBSERVABILITY: bool = True
    ADAMI_OTEL_EXPORTER: Literal["console", "otlp"] = "console"
    # When True and ADAMI_OTEL_EXPORTER=console, allow ConsoleSpanExporter to write spans to stdout.
    # Default False to avoid polluting interactive CLI output.
    ADAMI_OTEL_CONSOLE_EXPORT_ENABLED: bool = False
    # Step 8 — OTLP policy: sampling (see ``observability/otel_export_policy.resolve_trace_sampler``).
    # When unset, ``OTEL_TRACES_SAMPLER`` / ``OTEL_TRACES_SAMPLER_ARG`` apply (OpenTelemetry spec).
    ADAMI_OTEL_TRACES_SAMPLER: Optional[str] = None
    ADAMI_OTEL_TRACES_SAMPLER_RATIO: float = Field(default=1.0, ge=0.0, le=1.0)
    # Export-time span attribute / event redaction before OTLP or Console batch.
    ADAMI_OTEL_EXPORT_REDACT_ENABLED: bool = True
    ADAMI_OTEL_EXPORT_ATTR_VALUE_MAX_LEN: int = Field(default=2048, ge=64, le=65536)
    ADAMI_ENABLE_HITL: bool = False
    ADAMI_ENABLE_MULTI_TENANT: bool = False
    ADAMI_SKIP_DOCKER_SANDBOX: bool = True

    # ====================== 运行期 profile（生产安全 / Docker 沙箱） ======================
    # ``None`` = 自动：在 Linux 容器内（存在 ``/.dockerenv``）视为 ``production``，否则 ``development``。
    # ``production``：在未单独 export 覆盖时，强制走 Docker 技能沙箱（``ADAMI_SKIP_DOCKER_SANDBOX=false``）、
    # ``DEBUG=false``，并启用 DreamSandbox 的只读根文件系统 + 权能降级等（见下方 *DOCKER_SANDBOX*）。
    ADAMI_RUNTIME_PROFILE: Optional[Literal["development", "production"]] = None
    # DreamSandbox ``containers.run`` 加固（``production`` profile 会在未 export 时打开前两项）。
    ADAMI_DOCKER_SANDBOX_READ_ONLY_ROOTFS: bool = False
    ADAMI_DOCKER_SANDBOX_NO_NEW_PRIVILEGES: bool = True
    ADAMI_DOCKER_SANDBOX_DROP_ALL_CAPABILITIES: bool = False
    ADAMI_DOCKER_SANDBOX_TMPFS_TMP_MB: int = 256

    # ====================== MCP（工具协议 / Docker stdio server） ======================
    ADAMI_MCP_ENABLED: bool = False
    ADAMI_MCP_SERVERS_JSON: Optional[str] = None
    ADAMI_MCP_ALLOW_TOOLS: List[str] = []
    ADAMI_MCP_DENY_TOOLS: List[str] = []
    ADAMI_MCP_DOCKER_NETWORK_MODE: str = "bridge"
    ADAMI_MCP_TIMEOUT_SEC: float = 30.0
    # WEB_SEARCH tool timeout budget (seconds). This is distinct from MCP timeout.
    ADAMI_WEB_SEARCH_TIMEOUT_SEC: float = 30.0
    ADAMI_MCP_READ_ONLY_FS: bool = True
    ADAMI_MCP_MOUNT_ALLOWLIST: List[str] = []

    # mcp-agent（lastmile-ai）模块二总闸
    ADAMI_MCP_MODULE_AGENT_ENABLED: bool = True
    ADAMI_USE_MCP_AGENT_PLANNER: bool = True
    ADAMI_USE_MCP_AGENT: bool = True
    ADAMI_MCP_AGENT_LLM_PROVIDER: Optional[str] = None
    ADAMI_MCP_AGENT_PLAN_TYPE: str = "iterative"

    # ====================== Sim / 可回放轨迹（模块三，EventBus NDJSON） ======================
    # 模块三总闸：False 时 trace / replay / webhook 相关能力应尽量短路（默认 True，不强制开启导出）。
    ADAMI_SIM_MODULE_ENABLED: bool = True
    # CI / replay capture helper: when True, report providers and other integrations should avoid network calls.
    ADAMI_SIM_OFFLINE: bool = False
    ADAMI_SIM_TRACE_EXPORT_ENABLED: bool = False
    ADAMI_SIM_TRACE_EXPORT_PATH: Optional[str] = None
    ADAMI_SIM_TRACE_MAX_QUEUE: int = 4096
    ADAMI_SIM_TRACE_BATCH_SIZE: int = 64
    ADAMI_SIM_TRACE_FLUSH_INTERVAL_SEC: float = 0.25
    ADAMI_SIM_TRACE_TOPICS_ALLOWLIST: List[str] = []

    # Sim 自托管 Webhook 桥（步骤 3）
    ADAMI_SIM_WEBHOOK_ENABLED: bool = False
    ADAMI_SIM_WEBHOOK_URL: Optional[str] = None
    ADAMI_SIM_WEBHOOK_SECRET: Optional[str] = None
    ADAMI_SIM_WORKFLOW_ID: Optional[str] = None
    ADAMI_SIM_WEBHOOK_MODE: str = "envelope"
    ADAMI_SIM_WEBHOOK_TIMEOUT_SEC: float = 5.0

    # ====================== DeerFlow 对齐 / 长任务阶段（模块四） ======================
    # True 时，所有 compose 注册的工作流在 prepare 阶段自动初始化 current_phase / long_task_stages；
    # 亦可单独对某工作流设置 metadata.long_task_tracking_enabled=True。
    # 模块四默认开启：阶段闸 / checkpoint / 产物引用等能力在编排层自动生效。
    ADAMI_LONG_TASK_TRACKING_ENABLED: bool = True
    # 步骤 4：失败分类子串（小写匹配 error 文本）
    ADAMI_LONG_TASK_PHASE_FATAL_SUBSTRINGS: List[str] = [
        "401",
        "403",
        "forbidden",
        "unauthorized",
        "sandbox violation",
        "auth failed",
        "invalid api key",
    ]
    ADAMI_LONG_TASK_TRANSIENT_SUBSTRINGS: List[str] = [
        "timeout",
        "timed out",
        "temporarily unavailable",
        "503",
        "502",
        "connection reset",
        "econnreset",
    ]
    # 每工作流最多成功执行「last_good 回滚」次数，防止 phase_fatal 死循环
    ADAMI_WORKFLOW_PHASE_RECOVERY_MAX: int = 2
    # 步骤 5：长任务 TOOL 节点是否在独立 run 目录执行（产物进 StageArtifact 引用，不污染 toolbox.sandbox_dir 根）
    ADAMI_LONG_TASK_ISOLATED_TOOL_RUN: bool = True
    ADAMI_LONG_TASK_RUNS_DIR: Optional[str] = None

    # 步骤 6：外部 DeerFlow 侧车（HTTP/CLI 桥；不安装 deer-flow 包；默认关闭）
    ADAMI_DEERFLOW_ENABLED: bool = False
    ADAMI_DEERFLOW_BASE_URL: Optional[str] = None
    ADAMI_DEERFLOW_CLI_PATH: Optional[str] = None
    ADAMI_DEERFLOW_SUBMIT_PATH: str = "/api/adami/v1/delegate/submit"
    ADAMI_DEERFLOW_STATUS_PATH_TEMPLATE: str = "/api/adami/v1/delegate/tasks/{task_id}/status"
    ADAMI_DEERFLOW_RESULT_PATH_TEMPLATE: str = "/api/adami/v1/delegate/tasks/{task_id}/result"
    ADAMI_DEERFLOW_TOKEN: Optional[str] = None
    ADAMI_DEERFLOW_REQUIRE_TOKEN: bool = False
    ADAMI_DEERFLOW_TLS_CA_FILE: Optional[str] = None
    ADAMI_DEERFLOW_TLS_CLIENT_CERT_FILE: Optional[str] = None
    ADAMI_DEERFLOW_TLS_CLIENT_KEY_FILE: Optional[str] = None
    ADAMI_DEERFLOW_ALLOWED_HOSTS: List[str] = []
    ADAMI_DEERFLOW_REJECT_INSECURE_BIND_HOSTS: bool = True
    ADAMI_DEERFLOW_ALLOW_HTTP_LOCALHOST: bool = True
    ADAMI_DEERFLOW_POLL_INTERVAL_SEC: float = 2.0
    ADAMI_DEERFLOW_POLL_TIMEOUT_SEC: float = 3600.0
    ADAMI_DEERFLOW_HTTP_TIMEOUT_SEC: float = 30.0

    # ====================== last30days（模块五：外部 CLI 世界传感器，默认关闭） ======================
    # 设计目标：不引入 last30days 的重依赖；仅通过子进程调用外部脚本并落盘 SecondBrain。
    ADAMI_LAST30DAYS_ENABLED: bool = False
    # 外部安装的 last30days.py 绝对路径（例如 ~/.claude/skills/last30days/scripts/last30days.py）
    ADAMI_LAST30DAYS_SCRIPT_PATH: Optional[str] = None
    # 可选：指定 Python 解释器（需 3.12+）。未指定时由桥接层自行探测 python3.13/python3.12/python3。
    ADAMI_LAST30DAYS_PYTHON: Optional[str] = None
    # last30days.py --emit=MODE（官方包含 compact|json|md|context|path；本集成默认使用 context 或 md）
    ADAMI_LAST30DAYS_EMIT_MODE: str = "context"
    # 单次执行超时（秒）
    ADAMI_LAST30DAYS_TIMEOUT_SEC: float = 120.0
    # 是否默认附加 --refresh（绕过 last30days 自身缓存）
    ADAMI_LAST30DAYS_REFRESH_DEFAULT: bool = False
    # Report Studio「立即简报 / report run」：是否对 last30days 子进程加 --refresh（默认开，避免简报新闻滞后）
    ADAMI_REPORT_STUDIO_LAST30DAYS_REFRESH: bool = True
    # Report Studio 是否复用 last30days_bridge 进程内短缓存（默认关，避免与「立即生成」预期不符）
    ADAMI_REPORT_STUDIO_LAST30_CACHE_ENABLED: bool = False
    # 简报：外源条目按条翻译为目标语言（需 ADAMI_TRANSLATE_ENABLED 与可用 LLM）
    ADAMI_REPORT_TRANSLATE_NEWS: bool = True
    ADAMI_REPORT_TRANSLATE_MAX_ITEMS: int = 6
    # 简报：CoinGecko 现货（BTC/ETH/SOL）；关闭则跳过该节
    ADAMI_REPORT_CRYPTO_ENABLED: bool = True
    ADAMI_REPORT_CRYPTO_TIMEOUT_SEC: float = 12.0
    # 定时简报主题（由 circadian_nerve 触发；未设置则不触发）
    ADAMI_LAST30DAYS_DAILY_TOPIC: Optional[str] = None
    ADAMI_LAST30DAYS_WEEKLY_TOPIC: Optional[str] = None
    # 写入 SecondBrain 的目录（"Inbox" 或 "Resources"；具体校验由 ingest 层实现）
    ADAMI_LAST30DAYS_WRITE_TO: str = "Inbox"
    # 写入 SecondBrain 笔记文件名前缀
    ADAMI_LAST30DAYS_NOTE_PREFIX: str = "last30days"
    # 将简报正文（及标题）译为 ``effective_ui_default_locale()``；依赖 ``ADAMI_TRANSLATE_ENABLED`` 与可用 API Key。
    ADAMI_LAST30DAYS_TRANSLATE_DIGEST: bool = True
    # 假定 last30days CLI 输出主语言（与目标相同时跳过翻译以省调用）。
    ADAMI_LAST30DAYS_DIGEST_SOURCE_LOCALE: str = "en"

    # ====================== 【SelfTest 自我验证】 ======================
    ADAMI_ENABLE_SELF_TEST: bool = True
    ADAMI_SELF_TEST_TIMEOUT: int = 60
    ADAMI_SELF_TEST_CRITICAL_FILES: List[str] = ["test_workflow_engine.py", "test_reflexion.py"]
    ADAMI_SELF_TEST_FULL_FILES: List[str] = [
        "test_workflow_engine.py",
        "test_multi_agent.py",
        "test_reflexion.py",
        "test_tdd.py",
        "test_evolution.py",
    ]

    # ====================== 【主动进化】MetaCortex + EvolutionOrchestrator ======================
    ADAMI_AUTO_EVOLUTION_ENABLED: bool = True
    ADAMI_AUTO_EVOLUTION_INTERVAL_HOURS: int = 6

    # ====================== 【经验池 / 策略热更新 / Agent Lightning】 ======================
    ADAMI_EXPERIENCE_ENABLED: bool = True
    ADAMI_EXPERIENCE_DIR: Path = Path(".adami_data/experience")
    ADAMI_EXPERIENCE_FLUSH_INTERVAL_SEC: float = 5.0

    ADAMI_POLICY_DIR: Path = Path(".adami_data/policy")
    ADAMI_POLICY_RELOAD_INTERVAL_SEC: float = 60.0
    ADAMI_POLICY_MANIFEST_FILENAME: str = "manifest.json"

    # True: ``agl_compat`` kernel_sink（trace/奖励经 experience_sink；进程内不 import agentlightning Trainer）。
    ADAMI_AGL_ENABLED: bool = True
    ADAMI_AGL_STORE_URI: Optional[str] = None
    ADAMI_AGL_STORE_BACKEND: str = "memory"
    ADAMI_AGL_STORE_SQLITE_PATH: Optional[str] = None
    ADAMI_AGL_TRAIN_OUTPUT_DIR: Optional[str] = None

    # False: 不按墙钟跑 ``run_training_job``；需要离线训练时再设为 True。
    ADAMI_TRAIN_SCHEDULE_ENABLED: bool = False
    ADAMI_TRAIN_SCHEDULE_HOUR: int = 3
    ADAMI_TRAIN_SCHEDULE_MINUTE: int = 0
    ADAMI_TRAIN_SCHEDULE_TZ: str = "Asia/Shanghai"
    ADAMI_TRAIN_SCHEDULE_DRY_RUN: bool = False
    ADAMI_TRAIN_SCHEDULE_FALLBACK_DRY_RUN: bool = True
    ADAMI_TRAIN_SCHEDULE_MODE: str = "fit"
    ADAMI_TRAIN_SCHEDULE_ALGORITHM: str = "baseline"
    ADAMI_TRAIN_SCHEDULE_N_EPOCHS: int = 1
    ADAMI_TRAIN_SCHEDULE_N_RUNNERS: int = 1
    ADAMI_TRAIN_SCHEDULE_LIMIT: Optional[int] = None
    ADAMI_TRAIN_SCHEDULE_MAX_ROLLOUTS: Optional[int] = None
    ADAMI_TRAIN_SCHEDULE_EXECUTION_STRATEGY: str = "shared_memory"
    ADAMI_TRAIN_SCHEDULE_TRACER: str = "dummy"
    ADAMI_TRAIN_SCHEDULE_MANIFEST_VERSION: str = "0.1.0"
    ADAMI_TRAIN_SCHEDULE_MODEL_REF: Optional[str] = None
    ADAMI_TRAIN_SCHEDULE_RSYNC_DEST: Optional[str] = None

    # Idle-gated Agent Lightning：用户无交互超过阈值后触发一次 ``run_training_job``（与定时任务共享 ``train_job_lock``）。
    ADAMI_IDLE_TRAIN_ENABLED: bool = True
    ADAMI_IDLE_TRAIN_AFTER_SEC: float = 1800.0  # 30 minutes
    ADAMI_IDLE_TRAIN_POLL_SEC: float = 60.0
    ADAMI_IDLE_TRAIN_COOLDOWN_SEC: float = 14400.0  # min seconds between idle-triggered runs

    # ====================== 【并发 / HTTP 客户端 / 启动节律】 ======================
    # Max concurrent ``LifecycleManager`` consumer tasks processing ``system.events``.
    # Values > 1 allow different chats and events to overlap; kept low by default because
    # overlapping processing was a major source of duplicate replies / noisy CLI when
    # paired with Milestone A queue semantics. Operators who need Telegram throughput
    # across many chats may raise this explicitly.
    ADAMI_CURIOSITY_QUEUE_MAX: int = 64
    ADAMI_EVENT_CONSUMER_MAX_CONCURRENT: int = 1
    ADAMI_SUB_AGENT_MAX_CONCURRENT: int = 3
    ADAMI_ANS_SKILL_OPTIMIZE_MAX_PARALLEL: int = 2
    ADAMI_ROUTER_HTTP_TIMEOUT_SEC: float = 120.0
    ADAMI_ROUTER_OLLAMA_TIMEOUT_SEC: float = 120.0
    ADAMI_ROUTER_HTTP_MAX_KEEPALIVE_CONNECTIONS: int = 30
    ADAMI_ROUTER_HTTP_MAX_CONNECTIONS: int = 100
    ADAMI_BOOT_SKILL_CLEANER_INTERVAL_SEC: int = 86_400
    ADAMI_BOOT_SKILL_OPTIMIZER_INTERVAL_HOURS: int = 4
    # True: 若技能向量文档指纹与上次一致则跳过 ``rebuild_index`` 全量 upsert（仍会做孤儿 id 清理）
    ADAMI_VECTOR_STORE_SKIP_REBUILD_IF_UNCHANGED: bool = True

    # ====================== 【编排 / 多智能体：队列轮询与任务等待】 ======================
    ADAMI_ORCHESTRATOR_QUEUE_POLL_SEC: float = 1.0
    ADAMI_WORKFLOW_NODE_DEFAULT_TIMEOUT_SEC: int = 60
    # CLI: hard timeout for a single user task to avoid indefinite session lock holds.
    # When exceeded, DecisionProcessor will cancel the task, release the session lock,
    # and continue with queued tasks.
    ADAMI_CLI_TASK_HARD_TIMEOUT_SEC: float = 900.0
    # Telegram/Discord: hard timeout for a single user task to avoid indefinite session lock holds.
    # When exceeded, DecisionProcessor will cancel the task, release the session lock,
    # and continue with queued tasks.
    ADAMI_TASK_HARD_TIMEOUT_SEC: float = 900.0
    ADAMI_MULTI_AGENT_ENGINEER_WAIT_SEC: int = 300
    ADAMI_MULTI_AGENT_DEFAULT_WAIT_SEC: int = 120
    ADAMI_MULTI_AGENT_MIN_WAIT_SEC: int = 120

    # ====================== 【数据路径覆盖】 ======================
    ADAMI_L2_MEMORY_DB_PATH: Optional[str] = None
    ADAMI_CHROMA_PERSIST_DIR: Optional[str] = None
    ADAMI_EPISODIC_VECTOR_DB_PATH: Optional[str] = None
    ADAMI_SUBCONSCIOUS_DB_PATH: Optional[str] = None
    ADAMI_DLQ_DB_PATH: Optional[str] = None
    ADAMI_SECOND_BRAIN_ROOT: Optional[str] = None
    ADAMI_SKILL_MARKET_DIR: Optional[str] = None
    ADAMI_TEMP_SKILLS_DIR: Optional[str] = None
    ADAMI_FINAL_SKILLS_DIR: Optional[str] = None
    ADAMI_FAILED_SKILLS_DIR: Optional[str] = None
    ADAMI_SANDBOX_VOLUME_DIR: Optional[str] = None
    ADAMI_SANDBOX_TESTS_DIR: Optional[str] = None
    ADAMI_PLUGINS_SAFE_DIR: Optional[str] = None
    ADAMI_KERNEL_LOG_FILE: Optional[str] = None
    ADAMI_SELF_STATE_JSON_PATH: Optional[str] = None
    ADAMI_RL_WEIGHTS_PATH: Optional[str] = None
    ADAMI_KEYSTORE_JSON_PATH: Optional[str] = None
    ADAMI_BRAIN_CANDIDATES_RELATIVE: str = "System/working-memory/candidates.md"
    ADAMI_BRAIN_PROFILE_RELATIVE: str = "Identity/PROFILE.md"
    ADAMI_KERNEL_LOG_MAX_BYTES: int = 10 * 1024 * 1024
    ADAMI_KERNEL_LOG_BACKUP_COUNT: int = 5

    # ====================== 任务迭代重试配置 ======================
    ADAMI_COMPLEX_TASK_MAX_RETRIES: int = 3
    ADAMI_CREATE_SKILL_MAX_RETRIES: int = 3
    ADAMI_AUTO_EVOLUTION_MAX_RETRIES: int = 3

    @property
    def adami_data_dir_path(self) -> Path:
        return Path(str(self.ADAMI_DATA_DIR)).expanduser()

    def _or_under_data(self, override: Optional[str], *parts: str) -> str:
        if override and str(override).strip():
            return str(Path(override).expanduser())
        return str(self.adami_data_dir_path.joinpath(*parts))

    @property
    def path_l2_memory_db(self) -> str:
        return self._or_under_data(self.ADAMI_L2_MEMORY_DB_PATH, "l2_memory.db")

    @property
    def path_chroma_persist_dir(self) -> str:
        return self._or_under_data(self.ADAMI_CHROMA_PERSIST_DIR, "chroma")

    @property
    def path_episodic_vector_db(self) -> str:
        return self._or_under_data(self.ADAMI_EPISODIC_VECTOR_DB_PATH, "vector_db")

    @property
    def path_subconscious_db(self) -> str:
        return self._or_under_data(self.ADAMI_SUBCONSCIOUS_DB_PATH, "subconscious.db")

    @property
    def path_dlq_db(self) -> str:
        return self._or_under_data(self.ADAMI_DLQ_DB_PATH, "dlq.db")

    @property
    def path_second_brain_root(self) -> str:
        return self._or_under_data(self.ADAMI_SECOND_BRAIN_ROOT, "brain")

    @property
    def path_brain_candidates_md(self) -> str:
        return str(Path(self.path_second_brain_root) / self.ADAMI_BRAIN_CANDIDATES_RELATIVE)

    @property
    def path_brain_profile_md(self) -> str:
        return str(Path(self.path_second_brain_root) / self.ADAMI_BRAIN_PROFILE_RELATIVE)

    @property
    def path_skill_market_dir(self) -> str:
        return self._or_under_data(self.ADAMI_SKILL_MARKET_DIR, "market")

    @property
    def path_temp_skills_dir(self) -> str:
        return self._or_under_data(self.ADAMI_TEMP_SKILLS_DIR, "tmp_skills")

    @property
    def path_final_skills_dir(self) -> str:
        return self._or_under_data(self.ADAMI_FINAL_SKILLS_DIR, "skills")

    @property
    def path_failed_skills_dir(self) -> str:
        return self._or_under_data(self.ADAMI_FAILED_SKILLS_DIR, "failed_skills")

    @property
    def path_sandbox_volume_dir(self) -> str:
        return self._or_under_data(self.ADAMI_SANDBOX_VOLUME_DIR, "sandbox_volume")

    @property
    def path_long_task_runs_dir(self) -> str:
        """每 workflow 一次子进程沙箱 run 的根目录（默认 .adami_data/long_task_runs）。"""
        return self._or_under_data(self.ADAMI_LONG_TASK_RUNS_DIR, "long_task_runs")

    @property
    def path_task_queue_json(self) -> Path:
        """``task_queue.json`` 绝对路径（会话任务 FIFO 持久化）。"""
        if self.ADAMI_TASK_QUEUE_PATH and str(self.ADAMI_TASK_QUEUE_PATH).strip():
            return Path(str(self.ADAMI_TASK_QUEUE_PATH).strip()).expanduser()
        return self.adami_data_dir_path / "task_queue.json"

    @property
    def path_sandbox_tests_dir(self) -> str:
        if self.ADAMI_SANDBOX_TESTS_DIR and str(self.ADAMI_SANDBOX_TESTS_DIR).strip():
            return str(Path(self.ADAMI_SANDBOX_TESTS_DIR).expanduser())
        return str(self.adami_data_dir_path / "sandbox_volume" / "tests")

    @property
    def path_plugins_safe_dir(self) -> str:
        return self._or_under_data(self.ADAMI_PLUGINS_SAFE_DIR, "plugins")

    @property
    def path_kernel_log_file(self) -> str:
        return self._or_under_data(self.ADAMI_KERNEL_LOG_FILE, "kernel.log")

    @property
    def path_self_state_json(self) -> str:
        return self._or_under_data(self.ADAMI_SELF_STATE_JSON_PATH, "self_state.json")

    @property
    def path_rl_weights_json(self) -> str:
        return self._or_under_data(self.ADAMI_RL_WEIGHTS_PATH, "rl_weights.json")

    @property
    def path_keystore_json(self) -> str:
        return self._or_under_data(self.ADAMI_KEYSTORE_JSON_PATH, "keystore.json")

    @property
    def path_chat_locale_overrides_json(self) -> str:
        """每 chat 持久化语言偏好（Telegram chat_id / Discord channel_id 等字符串键）。"""
        return str(self.adami_data_dir_path / "chat_locale_overrides.json")

    def effective_ui_default_locale(self) -> str:
        """Wizard / 静态菜单等无 request context 时的 UI 默认语言标签。"""
        from adami_kernel.i18n.locale_utils import normalize_locale

        raw = self.ADAMI_UI_LOCALE
        if raw is not None and str(raw).strip():
            return normalize_locale(str(raw))
        sys_ui = str(getattr(self, "ADAMI_SYSTEM_UI_LOCALE", "") or "").strip()
        if sys_ui:
            return normalize_locale(sys_ui)
        return normalize_locale(self.ADAMI_DEFAULT_LOCALE)

    def effective_report_locale(self) -> str:
        """Report Studio 渲染默认语言（模板 + report.studio 标题键）；未单独配置时跟 UI 默认。"""
        from adami_kernel.i18n.locale_utils import normalize_locale

        raw = getattr(self, "ADAMI_REPORT_LOCALE", None)
        if raw is None or not str(raw).strip():
            return self.effective_ui_default_locale()
        return normalize_locale(str(raw))

    @property
    def resolved_experience_dir(self) -> Path:
        p = Path(self.ADAMI_EXPERIENCE_DIR)
        if p.is_absolute():
            return p
        parts = p.parts
        if parts and parts[0] == ".adami_data":
            return self.adami_data_dir_path.joinpath(*parts[1:])
        return self.adami_data_dir_path / p

    @property
    def resolved_policy_dir(self) -> Path:
        p = Path(self.ADAMI_POLICY_DIR)
        if p.is_absolute():
            return p
        parts = p.parts
        if parts and parts[0] == ".adami_data":
            return self.adami_data_dir_path.joinpath(*parts[1:])
        return self.adami_data_dir_path / p

    @model_validator(mode="after")
    def normalize_i18n_locale_settings(self) -> "Settings":
        from adami_kernel.i18n.locale_utils import normalize_locale

        seen: List[str] = []
        for x in self.ADAMI_SUPPORTED_LOCALES:
            n = normalize_locale(str(x))
            if n not in seen:
                seen.append(n)
        self.ADAMI_SUPPORTED_LOCALES = seen
        dd = normalize_locale(self.ADAMI_DEFAULT_LOCALE)
        if dd not in seen:
            logger.warning(
                "[CONFIG] ADAMI_DEFAULT_LOCALE=%r 不在 ADAMI_SUPPORTED_LOCALES 中，回退到 en（或列表首项）。",
                self.ADAMI_DEFAULT_LOCALE,
            )
            dd = "en" if "en" in seen else seen[0]
        self.ADAMI_DEFAULT_LOCALE = dd
        ui_raw = getattr(self, "ADAMI_UI_LOCALE", None)
        if ui_raw is not None and str(ui_raw).strip():
            nu = normalize_locale(str(ui_raw))
            if nu not in seen:
                logger.warning(
                    "[CONFIG] ADAMI_UI_LOCALE=%r 不在 ADAMI_SUPPORTED_LOCALES 中，将忽略 UI 覆盖。",
                    ui_raw,
                )
                self.ADAMI_UI_LOCALE = None
            else:
                self.ADAMI_UI_LOCALE = nu
        else:
            self.ADAMI_UI_LOCALE = None
        rep_raw = getattr(self, "ADAMI_REPORT_LOCALE", None)
        if rep_raw is not None and str(rep_raw).strip():
            nr = normalize_locale(str(rep_raw))
            if nr not in seen:
                logger.warning(
                    "[CONFIG] ADAMI_REPORT_LOCALE=%r 不在 ADAMI_SUPPORTED_LOCALES 中，将忽略简报语言覆盖。",
                    rep_raw,
                )
                self.ADAMI_REPORT_LOCALE = None
            else:
                self.ADAMI_REPORT_LOCALE = nr
        else:
            self.ADAMI_REPORT_LOCALE = None

        sys_ui_raw = str(getattr(self, "ADAMI_SYSTEM_UI_LOCALE", "") or "").strip()
        if sys_ui_raw:
            su = normalize_locale(sys_ui_raw)
            if su not in seen:
                logger.warning(
                    "[CONFIG] ADAMI_SYSTEM_UI_LOCALE=%r 不在 ADAMI_SUPPORTED_LOCALES 中，将回退为 zh-Hans。",
                    sys_ui_raw,
                )
                self.ADAMI_SYSTEM_UI_LOCALE = "zh-Hans" if "zh-Hans" in seen else seen[0]
            else:
                self.ADAMI_SYSTEM_UI_LOCALE = su
        else:
            self.ADAMI_SYSTEM_UI_LOCALE = "zh-Hans" if "zh-Hans" in seen else seen[0]
        return self

    @model_validator(mode="after")
    def resolve_and_apply_runtime_profile(self) -> "Settings":
        """解析 ``ADAMI_RUNTIME_PROFILE`` 并套用生产安全默认值（尊重已 export 的显式覆盖）。"""
        raw_profile = getattr(self, "ADAMI_RUNTIME_PROFILE", None)
        if raw_profile is None:
            in_container = Path("/.dockerenv").is_file()
            profile: Literal["development", "production"] = (
                "production" if in_container else "development"
            )
            self.ADAMI_RUNTIME_PROFILE = profile
            if in_container and "ADAMI_RUNTIME_PROFILE" not in os.environ:
                logger.info(
                    "[CONFIG] ADAMI_RUNTIME_PROFILE auto=%r (/.dockerenv present).",
                    profile,
                )
        else:
            profile = cast(Literal["development", "production"], raw_profile)

        if profile != "production":
            return self

        def _env_unset(name: str) -> bool:
            return name not in os.environ

        if _env_unset("ADAMI_SKIP_DOCKER_SANDBOX"):
            self.ADAMI_SKIP_DOCKER_SANDBOX = False
        if _env_unset("DEBUG"):
            self.DEBUG = False
        if _env_unset("ADAMI_DOCKER_SANDBOX_READ_ONLY_ROOTFS"):
            self.ADAMI_DOCKER_SANDBOX_READ_ONLY_ROOTFS = True
        if _env_unset("ADAMI_DOCKER_SANDBOX_DROP_ALL_CAPABILITIES"):
            self.ADAMI_DOCKER_SANDBOX_DROP_ALL_CAPABILITIES = True
        if _env_unset("ADAMI_DOCKER_SANDBOX_NO_NEW_PRIVILEGES"):
            self.ADAMI_DOCKER_SANDBOX_NO_NEW_PRIVILEGES = True

        if (
            profile == "production"
            and str(getattr(self, "ADAMI_MCP_DOCKER_NETWORK_MODE", "") or "").lower() == "host"
        ):
            logger.warning(
                "[CONFIG] production profile: ADAMI_MCP_DOCKER_NETWORK_MODE=host weakens isolation; "
                "prefer bridge unless strictly required.",
            )

        return self

    @model_validator(mode="after")
    def check_api_keys(self) -> "Settings":
        suspicious_patterns = [
            "your-api-key-here",
            "placeholder",
            "demo",
            "example",
            "none",
            "sk-placeholder",
            "sk-demo",
        ]
        min_key_length = 20

        for key_name in [
            "KIMI_API_KEY",
            "QWEN_API_KEY",
            "OPENAI_API_KEY",
            "GLM_API_KEY",
            "GEMINI_API_KEY",
            "GROK_API_KEY",
            "GROQ_API_KEY",
            "ANTHROPIC_API_KEY",
            "DEEPSEEK_API_KEY",
            "MINIMAX_API_KEY",
            "LLM_API_KEY",
            "TELEGRAM_BOT_TOKEN",
            "DISCORD_BOT_TOKEN",
            "GITHUB_TOKEN",
        ]:
            value = getattr(self, key_name, None)
            if value:
                val_str = str(value).strip().lower()
                if len(val_str) < min_key_length or any(p in val_str for p in suspicious_patterns):
                    if key_name in _PLACEHOLDER_SAFETY_WARNED:
                        continue
                    _PLACEHOLDER_SAFETY_WARNED.add(key_name)
                    from adami_kernel.i18n import t

                    logger.warning(
                        t(
                            "boot.config_safety_placeholder",
                            locale=self.effective_ui_default_locale(),
                            key_name=key_name,
                        )
                    )
        return self


def reload_settings() -> Settings:
    """重新实例化全局 ``settings``（例如 CLI 向导改写 cli_overrides.env 之后）。"""
    global settings
    _PLACEHOLDER_SAFETY_WARNED.clear()
    settings = Settings(_env_file=_settings_env_files(), _env_file_encoding="utf-8")
    try:
        from adami_kernel.i18n.bootstrap import bootstrap_i18n_defaults_from_settings

        bootstrap_i18n_defaults_from_settings()
    except Exception as e:  # pragma: no cover
        logger.debug("[CONFIG] i18n bootstrap after reload skipped: %s", e)
    return settings


settings = Settings(_env_file=_settings_env_files(), _env_file_encoding="utf-8")
try:
    from adami_kernel.i18n.bootstrap import bootstrap_i18n_defaults_from_settings

    bootstrap_i18n_defaults_from_settings()
except Exception as _e:  # pragma: no cover
    logger.debug("[CONFIG] i18n bootstrap on import skipped: %s", _e)


def mcp_agent_module_master_enabled(obj: Optional[Settings] = None) -> bool:
    s = obj if obj is not None else settings
    return bool(getattr(s, "ADAMI_MCP_MODULE_AGENT_ENABLED", True))


def mcp_agent_tool_execution_effective(obj: Optional[Settings] = None) -> bool:
    s = obj if obj is not None else settings
    return mcp_agent_module_master_enabled(s) and bool(s.ADAMI_USE_MCP_AGENT)


def mcp_agent_planner_pilot_effective(obj: Optional[Settings] = None) -> bool:
    s = obj if obj is not None else settings
    return mcp_agent_module_master_enabled(s) and bool(s.ADAMI_USE_MCP_AGENT_PLANNER)


def sim_module_master_enabled(obj: Optional[Settings] = None) -> bool:
    """模块三（Sim）总闸；False 时相关导出/桥接路径应短路。"""
    s = obj if obj is not None else settings
    return bool(getattr(s, "ADAMI_SIM_MODULE_ENABLED", True))


def markitdown_effective_enabled(obj: Optional[Settings] = None) -> bool:
    """Whether ``multi_modal`` should invoke the MarkItDown path for whitelisted suffixes.

    See ``ADAMI_MARKITDOWN_ENABLED`` on ``Settings`` (default ``True`` = force attempt; ``None`` = auto; ``False`` = off).
    """
    import importlib.util

    s = obj if obj is not None else settings
    flag = getattr(s, "ADAMI_MARKITDOWN_ENABLED", None)
    if flag is False:
        return False
    if flag is True:
        return True
    return importlib.util.find_spec("markitdown") is not None


# ====================== HybridLLMRouter 提供商表（非密钥；密钥仍从 settings 字段注入） ======================
ROUTER_THINK_PROVIDER_SPECS: list[dict[str, str]] = [
    {
        "name": "deepseek-r1",
        "base_url": "https://api.deepseek.com/v1/chat/completions",
        "model": "deepseek-reasoner",
        "format": "openai",
        "api_key_field": "DEEPSEEK_API_KEY",
    },
    {
        "name": "grok-4.20-reasoning",
        "base_url": "https://api.x.ai/v1/chat/completions",
        "model": "grok-4.20-beta-0309-reasoning",
        "format": "openai",
        "api_key_field": "GROK_API_KEY",
    },
    {
        "name": "kimi-k2.5",
        "base_url": "https://api.moonshot.cn/v1/chat/completions",
        "model": "moonshot-v1-auto",
        "format": "openai",
        "api_key_field": "KIMI_API_KEY",
    },
]

ROUTER_ACTION_PROVIDER_SPECS: list[dict[str, str]] = [
    {
        "name": "deepseek-v3.2",
        "base_url": "https://api.deepseek.com/v1/chat/completions",
        "model": "deepseek-chat",
        "format": "openai",
        "api_key_field": "DEEPSEEK_API_KEY",
    },
    {
        "name": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1/chat/completions",
        "model": "gpt-4o-mini",
        "format": "openai",
        "api_key_field": "OPENAI_API_KEY",
    },
    {
        "name": "groq-fast",
        "base_url": "https://api.groq.com/openai/v1/chat/completions",
        "model": "llama-4-70b-preview",
        "format": "openai",
        "api_key_field": "GROQ_API_KEY",
    },
    {
        "name": "minimax-abab7",
        "base_url": "https://api.minimax.chat/v1/text/chatcompletion_v2",
        "model": "abab7-chat",
        "format": "openai",
        "api_key_field": "MINIMAX_API_KEY",
    },
    {
        "name": "qwen3-plus",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
        "model": "qwen3-plus",
        "format": "openai",
        "api_key_field": "QWEN_API_KEY",
    },
    {
        "name": "gemini-3.1-flash",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "model": "gemini-3.1-flash",
        "format": "openai",
        "api_key_field": "GEMINI_API_KEY",
    },
    {
        "name": "glm-4-flash",
        "base_url": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
        "model": "glm-4-flash",
        "format": "openai",
        "api_key_field": "GLM_API_KEY",
    },
]


def _hydrate_router_provider_specs(specs: list[dict[str, str]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for spec in specs:
        key = getattr(settings, spec["api_key_field"], None)
        out.append(
            {
                "name": spec["name"],
                "base_url": spec["base_url"],
                "api_key": key,
                "model": spec["model"],
                "format": spec.get("format", "openai"),
            }
        )
    return out


def get_router_think_providers() -> list[dict[str, Any]]:
    return _hydrate_router_provider_specs(ROUTER_THINK_PROVIDER_SPECS)


def get_router_action_providers() -> list[dict[str, Any]]:
    return _hydrate_router_provider_specs(ROUTER_ACTION_PROVIDER_SPECS)
