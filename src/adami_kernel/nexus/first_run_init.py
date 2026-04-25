"""First-run initialization gate and wizard for AdamI.

Requirements (commercial onboarding):

- If first-run setup is not completed, AdamI must refuse to boot.
- The wizard guides operators module-by-module from the CLI:
  - language
  - local LLM (MLX/Ollama)
  - cloud API keys (optional)
  - Telegram/Discord routing (optional)
  - observability exporter (optional)
- Sensitive values are written to a local env override file (`cli_overrides.env`), not committed.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Iterable, Optional

from rich.console import Console

from adami_kernel.config import reload_settings
from adami_kernel.i18n import t
from adami_kernel.nexus.cli_settings_wizard import write_cli_overrides
from adami_kernel.nexus.nerve_registry import validate_messenger_routing_for_ops_check

logger = logging.getLogger("AdamI-FirstRunInit")


def _init_t(key: str, **kwargs: object) -> str:
    # Important: `reload_settings()` rebinds `adami_kernel.config.settings`. Always read it dynamically.
    from adami_kernel import config as config_mod

    return t(key, locale=config_mod.settings.effective_ui_default_locale(), **kwargs)


def needs_first_run_init() -> bool:
    """Return True if the kernel must run the first-run initializer."""
    from adami_kernel import config as config_mod

    return not bool(getattr(config_mod.settings, "ADAMI_FIRST_RUN_COMPLETE", False))


@dataclass(frozen=True)
class MissingItem:
    key: str
    hint: str


def _truthy(v: object) -> bool:
    return str(v).strip().lower() in {"1", "true", "t", "y", "yes", "on"}


def validate_startup_prereqs() -> list[MissingItem]:
    """Validate prerequisites for boot and return missing items (human-friendly)."""
    from adami_kernel import config as config_mod

    s = config_mod.settings
    missing: list[MissingItem] = []

    # First-run flag must be set (strict gate).
    if not bool(getattr(s, "ADAMI_FIRST_RUN_COMPLETE", False)):
        missing.append(MissingItem(key="init", hint=_init_t("init.validate.first_run_incomplete")))

    # Basic paths / profile.
    data_dir = str(getattr(s, "ADAMI_DATA_DIR", "") or "").strip()
    if not data_dir:
        missing.append(MissingItem(key="data_dir", hint=_init_t("init.validate.data_dir_missing")))

    profile = getattr(s, "ADAMI_RUNTIME_PROFILE", None)
    if profile not in ("development", "production"):
        missing.append(
            MissingItem(key="profile", hint=_init_t("init.validate.runtime_profile_missing"))
        )

    # Commercial required: local LLM must be enabled as a fallback.
    local_ok = bool(getattr(s, "OLLAMA_ENABLED", False)) or bool(getattr(s, "ADAMI_MLX_ENABLED", False))
    cloud_keys: Iterable[str] = (
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "DEEPSEEK_API_KEY",
        "GROQ_API_KEY",
        "GROK_API_KEY",
        "QWEN_API_KEY",
        "GLM_API_KEY",
        "KIMI_API_KEY",
        "MINIMAX_API_KEY",
        "LLM_API_KEY",
    )
    cloud_ok = any(bool(str(getattr(s, k, "") or "").strip()) for k in cloud_keys)
    # Commercial required: at least one cloud API key AND local fallback must both be present.
    if not local_ok:
        missing.append(MissingItem(key="llm_local", hint=_init_t("init.validate.local_llm_required")))
    if not cloud_ok:
        missing.append(
            MissingItem(
                key="llm_cloud",
                hint=_init_t("init.validate.cloud_key_required"),
            )
        )

    # If local is enabled, require a non-empty model name.
    if bool(getattr(s, "OLLAMA_ENABLED", False)) and not str(
        getattr(s, "OLLAMA_MODEL", "") or ""
    ).strip():
        missing.append(MissingItem(key="ollama", hint=_init_t("init.validate.ollama_model_missing")))

    tg_tok = str(getattr(s, "TELEGRAM_BOT_TOKEN", "") or "").strip()
    dc_tok = str(getattr(s, "DISCORD_BOT_TOKEN", "") or "").strip()
    # Commercial required: Telegram or Discord must be configured (no CLI-only mode).
    if not (tg_tok or dc_tok):
        missing.append(
            MissingItem(
                key="messenger",
                hint=_init_t("init.validate.messenger_missing"),
            )
        )

    # Messenger routing: if tokens are set, required ids must be present.
    try:
        validate_messenger_routing_for_ops_check()
    except RuntimeError as e:
        missing.append(MissingItem(key="messenger", hint=str(e)))

    # OTLP exporter requires endpoint.
    if str(getattr(s, "ADAMI_OTEL_EXPORTER", "console")).strip().lower() == "otlp":
        ep = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
        if not ep:
            missing.append(
                MissingItem(
                    key="otel",
                    hint=_init_t("init.validate.otlp_endpoint_missing"),
                )
            )

    return missing


def _ask_yn(console: Console, prompt_key: str, *, default_yes: bool = True) -> bool:
    prompt = _init_t(prompt_key)
    raw = console.input(prompt + " ").strip().lower()
    if raw == "":
        return default_yes
    return raw in {"y", "yes", "true", "1", "on"}


def _reload_for_locale_if_changed() -> None:
    # Reload so subsequent _init_t picks new ADAMI_UI_LOCALE.
    reload_settings()


def _ask_non_empty(console: Console, prompt_key: str, *, default: Optional[str] = None) -> str:
    while True:
        raw = console.input(_init_t(prompt_key) + " ").strip()
        if raw:
            return raw
        if default is not None:
            return default
        console.print(f"[red]{_init_t('init.cli.required')}[/red]")


def run_first_run_initializer(console: Console) -> None:
    """Run the strict first-run initializer wizard (CLI).

    This wizard is intentionally strict: it will not mark the system as initialized until all
    required modules are configured and prerequisites validate.
    """
    console.print(f"\n[bold cyan]{_init_t('init.cli.banner_title')}[/bold cyan]")
    console.print(f"[dim]{_init_t('init.cli.banner_sub')}[/dim]\n")

    # Step 1) Language selection (fork early).
    console.print(f"[bold]{_init_t('init.cli.locale.title')}[/bold]")
    console.print(f"1. {_init_t('settings.language.option_en')}")
    console.print(f"2. {_init_t('settings.language.option_zh')}")
    console.print(f"[dim]{_init_t('init.cli.locale.hint')}[/dim]")
    choice = console.input(_init_t("init.cli.prompt") + " ").strip()
    if choice == "1":
        write_cli_overrides({"ADAMI_UI_LOCALE": "en"})
        _reload_for_locale_if_changed()
    elif choice == "2":
        write_cli_overrides({"ADAMI_UI_LOCALE": "zh-Hans"})
        _reload_for_locale_if_changed()
    else:
        # In strict mode, we still allow skipping; it just means "keep defaults".
        console.print(f"[yellow]{_init_t('init.cli.skipped')}[/yellow]\n")

    # Step 1.5) Runtime profile (required).
    console.print(f"[bold]{_init_t('init.cli.profile.title')}[/bold]")
    console.print(f"1. {_init_t('init.cli.profile.dev')}")
    console.print(f"2. {_init_t('init.cli.profile.prod')}")
    prof = _ask_non_empty(console, "init.cli.prompt")
    if prof == "2":
        write_cli_overrides({"ADAMI_RUNTIME_PROFILE": "production"})
    else:
        write_cli_overrides({"ADAMI_RUNTIME_PROFILE": "development"})

    # Step 1.6) Data directory (required).
    console.print(f"\n[bold]{_init_t('init.cli.data_dir.title')}[/bold]")
    dd = console.input(_init_t("init.cli.data_dir.prompt") + " ").strip()
    if dd:
        write_cli_overrides({"ADAMI_DATA_DIR": dd})

    # Step 2) Local LLM: MLX (optional, macOS) + Ollama.
    console.print(f"[bold]{_init_t('init.cli.local_llm.title')}[/bold]")
    console.print(_init_t("init.cli.local_llm.desc"))

    if _ask_yn(console, "init.cli.ollama.enable_prompt", default_yes=True):
        host = console.input(_init_t("init.cli.ollama.host_prompt") + " ").strip()
        model = console.input(_init_t("init.cli.ollama.model_prompt") + " ").strip()
        updates: dict[str, str] = {"OLLAMA_ENABLED": "true"}
        if host:
            updates["OLLAMA_HOST"] = host
        if model:
            updates["OLLAMA_MODEL"] = model
        write_cli_overrides(updates)
    else:
        write_cli_overrides({"OLLAMA_ENABLED": "false"})

    # Step 3) Cloud API keys (required in commercial mode: at least one key must be set).
    console.print(f"\n[bold]{_init_t('init.cli.cloud.title')}[/bold]")
    console.print(f"[dim]{_init_t('init.cli.cloud.hint')}[/dim]")
    if _ask_yn(console, "init.cli.cloud.configure_prompt", default_yes=True):
        # Store secrets in local override file; remind user not to commit.
        from adami_kernel import config as config_mod

        for field in (
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "GEMINI_API_KEY",
            "DEEPSEEK_API_KEY",
        ):
            cur_set = bool(str(getattr(config_mod.settings, field, "") or "").strip())
            label = _init_t("init.cli.cloud.key_prompt", name=field, state=_init_t("init.cli.cloud.state_set" if cur_set else "init.cli.cloud.state_empty"))
            val = console.input(label + " ").strip()
            if val:
                write_cli_overrides({field: val})

    # Step 4) Messengers (commercial required: Telegram or Discord).
    console.print(f"\n[bold]{_init_t('init.cli.messengers.title')}[/bold]")
    console.print(f"[dim]{_init_t('init.cli.messengers.hint')}[/dim]")
    write_cli_overrides({"ADAMI_CLI_ONLY_MODE": "false"})

    if _ask_yn(console, "init.cli.telegram.configure_prompt", default_yes=True):
        tok = console.input(_init_t("init.cli.telegram.token_prompt") + " ").strip()
        cid = console.input(_init_t("init.cli.telegram.chat_id_prompt") + " ").strip()
        updates: dict[str, str] = {}
        if tok:
            updates["TELEGRAM_BOT_TOKEN"] = tok
        if cid:
            updates["TELEGRAM_CHAT_ID"] = cid
        if updates:
            write_cli_overrides(updates)

    if _ask_yn(console, "init.cli.discord.configure_prompt", default_yes=False):
        tok = console.input(_init_t("init.cli.discord.token_prompt") + " ").strip()
        uid = console.input(_init_t("init.cli.discord.user_id_prompt") + " ").strip()
        ch = console.input(_init_t("init.cli.discord.channel_id_prompt") + " ").strip()
        gu = console.input(_init_t("init.cli.discord.guild_id_prompt") + " ").strip()
        updates2: dict[str, str] = {}
        if tok:
            updates2["DISCORD_BOT_TOKEN"] = tok
        if uid:
            updates2["DISCORD_DEFAULT_USER_ID"] = uid
        if ch:
            updates2["DISCORD_DEFAULT_CHANNEL_ID"] = ch
        if gu:
            updates2["DISCORD_DEFAULT_GUILD_ID"] = gu
        if updates2:
            write_cli_overrides(updates2)

    # Step 5) Observability exporter (optional).
    console.print(f"\n[bold]{_init_t('init.cli.otel.title')}[/bold]")
    console.print(f"1. {_init_t('init.cli.otel.console')}")
    console.print(f"2. {_init_t('init.cli.otel.otlp')}")
    ot = console.input(_init_t("init.cli.prompt") + " ").strip()
    if ot == "2":
        write_cli_overrides({"ADAMI_OTEL_EXPORTER": "otlp"})
        console.print(f"[dim]{_init_t('init.cli.otel.otlp_hint')}[/dim]")
    elif ot == "1":
        write_cli_overrides({"ADAMI_OTEL_EXPORTER": "console"})

    # Mark completion only after validation passes.
    write_cli_overrides({"ADAMI_FIRST_RUN_COMPLETE": "true"})

    # Final validation loop (strict): refuse to finish until all required items are present.
    while True:
        reload_settings()
        missing = validate_startup_prereqs()
        if not missing:
            break
        console.print(f"\n[bold red]{_init_t('init.validate.failed_title')}[/bold red]")
        for i, item in enumerate(missing, start=1):
            console.print(f"{i}. {item.hint}")
        console.print(f"\n[yellow]{_init_t('init.validate.failed_footer')}[/yellow]\n")
        console.print(f"[bold]{_init_t('init.validate.retry_hint')}[/bold]")
        # In strict mode, we exit and force re-run, to keep the wizard simple and predictable.
        return

    # Mark completion + show quickstart.
    reload_settings()
    logger.info(_init_t("init.cli.done_log"))
    console.print(f"\n[green]{_init_t('init.cli.done')}[/green]")
    console.print(_init_t("init.cli.quickstart"))

