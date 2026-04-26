# src/adami_kernel/nexus/cli_settings_wizard.py
"""CLI 交互式配置向导：按类别浏览/修改 Settings 字段，写入 cli_overrides.env。"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from types import UnionType
from typing import Any, Dict, List, Optional, Tuple, Union, get_args, get_origin

from dotenv import dotenv_values
from rich.console import Console
from rich.table import Table

from adami_kernel.config import Settings, cli_overrides_env_path, reload_settings
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.boot_msg import boot_t

logger = logging.getLogger("AdamI-CLISettings")


def _wizard_t(key: str, **kwargs: Any) -> str:
    from adami_kernel.config import settings as _s

    return i18n_t(key, locale=_s.effective_ui_default_locale(), **kwargs)


_TRUTHY = frozenset({"1", "true", "t", "yes", "y", "on"})
_FALSEY = frozenset({"0", "false", "f", "no", "n", "off"})

_CATEGORIES: List[Tuple[str, str]] = [
    ("general", "settings.category.general"),
    ("language", "settings.category.language"),
    ("last30days", "settings.category.last30days"),
    ("data_paths", "settings.category.data_paths"),
    ("secrets", "settings.category.secrets"),
    ("models_local", "settings.category.models_local"),
    ("graph_memory", "settings.category.graph_memory"),
    ("skill_github", "settings.category.skill_github"),
    ("feature_switches", "settings.category.feature_switches"),
    ("mcp", "settings.category.mcp"),
    ("sim", "settings.category.sim"),
    ("orchestration", "settings.category.orchestration"),
    ("experience_policy", "settings.category.experience_policy"),
    ("concurrency_router", "settings.category.concurrency_router"),
    ("resources", "settings.category.resources"),
    ("self_test", "settings.category.self_test"),
    ("auto_evolution", "settings.category.auto_evolution"),
    ("retries", "settings.category.retries"),
    ("other", "settings.category.other"),
]


def _category_title(label_or_key: str) -> str:
    # If it's an i18n key, translate; otherwise treat as literal label.
    return _wizard_t(label_or_key) if label_or_key.startswith("settings.") else label_or_key

_MCP_SERVERS_JSON_TEMPLATE = (
    "[\n"
    "  {\n"
    '    "name": "dummy",\n'
    '    "image": "python:3.13-slim",\n'
    '    "command": ["python", "/sandbox/mcp_dummy_server.py"],\n'
    '    "args": [],\n'
    '    "env": {},\n'
    '    "workdir": "/sandbox",\n'
    '    "mounts": [\n'
    '      {"source": ".adami_data/sandbox_volume", "target": "/sandbox", "mode": "ro"}\n'
    "    ]\n"
    "  }\n"
    "]\n"
)


def mcp_servers_json_template() -> str:
    """给 ADAMI_MCP_SERVERS_JSON 的可复制模板（尽量短，适合粘贴到 CLI/聊天端）。"""
    return _MCP_SERVERS_JSON_TEMPLATE


def _category_id_for_field(name: str) -> str:
    if name in ("DEBUG", "ADAMI_HEALTH_PORT"):
        return "general"
    if name in (
        "ADAMI_DEFAULT_LOCALE",
        "ADAMI_SUPPORTED_LOCALES",
        "ADAMI_UI_LOCALE",
        "ADAMI_SYSTEM_UI_LOCALE",
    ):
        return "language"
    if name.startswith("ADAMI_LAST30DAYS_"):
        return "last30days"
    if name.endswith("_MAX_RETRIES"):
        return "retries"
    if name == "ADAMI_GRAPH_MEMORY_SQLITE_PATH":
        return "graph_memory"
    if (
        name == "ADAMI_DATA_DIR"
        or "PATH" in name
        or "_FILE" in name
        or "ROOT" in name
        or name in ("ADAMI_EXPERIENCE_DIR", "ADAMI_POLICY_DIR")
        or (
            "_DIR" in name
            and name.startswith("ADAMI_")
            and "TRAIN" not in name
            and "SCHEDULE" not in name
        )
        or name.startswith("ADAMI_BRAIN_")
        and name.endswith("_RELATIVE")
        or name in ("ADAMI_KERNEL_LOG_MAX_BYTES", "ADAMI_KERNEL_LOG_BACKUP_COUNT")
    ):
        return "data_paths"
    if name.endswith("_API_KEY") or name.endswith("_TOKEN") or name == "LLM_API_KEY":
        return "secrets"
    if (
        name
        in ("ADAMI_FAST_MODEL", "ADAMI_THINK_MODEL", "ADAMI_SUBCONSCIOUS_MODEL", "LLM_BASE_URL")
        or name.startswith("OLLAMA_")
        or name.startswith("ADAMI_MLX_")
    ):
        return "models_local"
    if (
        name.startswith("ADAMI_SKILL_")
        or name.startswith("ADAMI_GITHUB_")
        or name == "ADAMI_USAGE_THRESHOLD"
        or name.startswith("ADAMI_CREATE_SKILL_")
    ):
        return "skill_github"
    if name.startswith("ADAMI_USE_MCP_AGENT"):
        return "mcp"
    if name.startswith("ADAMI_SIM_"):
        return "sim"
    if (
        name.startswith("ADAMI_USE_")
        or name.startswith("ADAMI_ENABLE_")
        or name.startswith("ADAMI_SKIP_")
    ):
        return "feature_switches"
    if name.startswith("ADAMI_MCP_"):
        return "mcp"
    if (
        name.startswith("ADAMI_WORKFLOW_")
        or name.startswith("ADAMI_ORCHESTRATOR_")
        or name.startswith("ADAMI_MULTI_AGENT_")
        or name == "ADAMI_SKILL_TIMEOUT"
    ):
        return "orchestration"
    if (
        name.startswith("ADAMI_EXPERIENCE_")
        or name.startswith("ADAMI_POLICY_")
        or name.startswith("ADAMI_AGL_")
        or name.startswith("ADAMI_TRAIN_SCHEDULE_")
    ):
        return "experience_policy"
    if (
        name.startswith("ADAMI_EVENT_")
        or name.startswith("ADAMI_SUB_AGENT_")
        or name.startswith("ADAMI_ANS_")
        or name.startswith("ADAMI_ROUTER_")
        or name.startswith("ADAMI_BOOT_")
    ):
        return "concurrency_router"
    if name.startswith("ADAMI_CRITICAL_") or name.startswith("ADAMI_CPU_"):
        return "resources"
    if name.startswith("ADAMI_SELF_TEST_"):
        return "self_test"
    if name.startswith("ADAMI_AUTO_EVOLUTION"):
        return "auto_evolution"
    return "other"


def _is_secret_field(name: str) -> bool:
    return bool(
        name.endswith("_API_KEY")
        or name.endswith("_TOKEN")
        or name.endswith("_PASSWORD")
        or name == "LLM_API_KEY"
    )


def _strip_optional(annotation: Any) -> Any:
    origin = get_origin(annotation)
    if origin is Union or origin is UnionType:
        args = [a for a in get_args(annotation) if a is not type(None)]
        if len(args) == 1:
            return _strip_optional(args[0])
    return annotation


def _coerce_value(name: str, annotation: Any, raw: str) -> Any:
    raw_stripped = raw.strip()
    if name == "ADAMI_UI_LOCALE" and raw_stripped.lower() in ("clear", "none", "-", ""):
        return None
    ann = _strip_optional(annotation)
    origin = get_origin(ann)

    if ann is bool:
        low = raw_stripped.lower()
        if low in _TRUTHY:
            return True
        if low in _FALSEY:
            return False
        raise ValueError(_wizard_t("settings.coerce.bool_hint"))

    if ann is int:
        return int(raw_stripped)

    if ann is float:
        return float(raw_stripped)

    if ann is Path or (origin is None and ann == Path):
        return Path(raw_stripped)

    if origin is list:
        args = get_args(ann)
        if args and args[0] is str:
            try:
                val = json.loads(raw_stripped)
            except json.JSONDecodeError as e:
                raise ValueError(_wizard_t("settings.coerce.list_json_error", detail=str(e))) from e
            if not isinstance(val, list) or not all(isinstance(x, str) for x in val):
                raise ValueError(_wizard_t("settings.coerce.list_strings_only"))
            return val

    if ann is str or ann is Any or origin is None:
        return raw_stripped

    raise ValueError(
        _wizard_t("settings.coerce.unsupported_type", path=str(cli_overrides_env_path()))
    )


def _format_stored_value(val: Any) -> str:
    if val is None:
        return ""
    if isinstance(val, bool):
        return "true" if val else "false"
    if isinstance(val, Path):
        return str(val)
    if isinstance(val, list):
        return json.dumps(list(val), ensure_ascii=False)
    return str(val)


def _display_value(name: str, val: Any) -> str:
    if val is None:
        return _wizard_t("settings.display.empty")
    if _is_secret_field(name) and val:
        return (
            _wizard_t("settings.display.secret_set")
            if str(val).strip()
            else _wizard_t("settings.display.empty")
        )
    if isinstance(val, list):
        return json.dumps(val, ensure_ascii=False)[:120]
    return str(val)


def _read_merged_env(path: Path) -> Dict[str, str]:
    if not path.is_file():
        return {}
    raw = dotenv_values(path)
    return {k: v for k, v in raw.items() if v is not None and str(v).strip() != ""}


def write_cli_overrides(updates: Dict[str, Optional[str]]) -> None:
    path = cli_overrides_env_path()
    merged = _read_merged_env(path)
    for key, val in updates.items():
        if val is None or val.strip() == "":
            merged.pop(key, None)
        else:
            merged[key] = val.strip()
    path.parent.mkdir(parents=True, exist_ok=True)
    header = (
        "# AdamI CLI overrides (written by the config wizard; loaded after project root .env)\n"
        "# Remove a key or clear its value, save, then choose r/reload in the wizard to fall back.\n\n"
    )
    lines = [header]
    for key in sorted(merged.keys()):
        v = merged[key]
        if any(ch in v for ch in " \n=\"'"):
            esc = v.replace("\\", "\\\\").replace('"', '\\"')
            lines.append(f'{key}="{esc}"\n')
        else:
            lines.append(f"{key}={v}\n")
    path.write_text("".join(lines), encoding="utf-8")
    logger.info(boot_t("boot.log.cli_overrides_written", path=str(path)))


def _fields_by_category() -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {cid: [] for cid, _ in _CATEGORIES}
    for fname in sorted(Settings.model_fields.keys()):
        cid = _category_id_for_field(fname)
        out.setdefault(cid, []).append(fname)
    return out


async def _readline(console: Console) -> str:
    line = await asyncio.to_thread(sys.stdin.readline)
    if not line:
        raise EOFError
    return line.rstrip("\r\n")


async def run_cli_settings_wizard(console: Console) -> None:
    """
    分类菜单；进入子类后逐项改值。
    写入文件见 `cli_overrides_env_path()`；改完后可 ``reload`` 热加载（部分子系统仍建议重启内核）。
    """
    console.print(f"\n[bold cyan]{_wizard_t('settings.cli.banner_title')}[/bold cyan]")
    console.print(
        f"[dim]{_wizard_t('settings.cli.banner_sub', path=str(cli_overrides_env_path()))}[/dim]\n"
    )

    by_cat = _fields_by_category()

    while True:
        table = Table(
            title=_wizard_t("settings.cli.table_categories_title"),
            show_header=True,
            header_style="bold",
        )
        table.add_column("#", style="cyan", justify="right")
        table.add_column(_wizard_t("settings.cli.col_category"), style="green")
        table.add_column(_wizard_t("settings.cli.col_hint"), style="dim")
        table.add_row(
            "0", _wizard_t("settings.cli.exit_wizard"), _wizard_t("settings.cli.exit_hint")
        )
        for i, (cid, title_key) in enumerate(_CATEGORIES, start=1):
            n = len(by_cat.get(cid, []))
            table.add_row(
                str(i), _category_title(title_key), _wizard_t("settings.cli.items_count", count=n)
            )
        console.print(table)
        console.print(f"[bold]{_wizard_t('settings.cli.pick_category')}[/bold]: ", end="")
        sys.stdout.flush()
        try:
            choice = await _readline(console)
        except EOFError:
            break
        choice = choice.strip()
        if choice == "0" or choice == "":
            console.print(f"[dim]{_wizard_t('settings.cli.exited')}[/dim]\n")
            break
        if choice.lower() == "reload":
            reload_settings()
            console.print(f"[green]{_wizard_t('settings.cli.reload_ok')}[/green]\n")
            continue
        try:
            idx = int(choice)
        except ValueError:
            console.print(f"[red]{_wizard_t('settings.cli.enter_number')}[/red]\n")
            continue
        if idx < 1 or idx > len(_CATEGORIES):
            console.print(f"[red]{_wizard_t('settings.cli.invalid_index')}[/red]\n")
            continue
        cid, _title_key = _CATEGORIES[idx - 1]
        fields = by_cat.get(cid, [])
        if not fields:
            console.print(f"[yellow]{_wizard_t('settings.cli.category_empty')}[/yellow]\n")
            continue

        await _category_submenu(console, cid, fields)

        by_cat = _fields_by_category()


async def _category_submenu(console: Console, category_id: str, fields: List[str]) -> None:
    from adami_kernel import config as config_mod

    title_key = next((k for cid, k in _CATEGORIES if cid == category_id), "settings.category.other")
    title = _category_title(title_key)
    s = config_mod.settings

    while True:
        console.print(
            f"\n[bold green]── {title} ──[/bold green] [dim]| {_wizard_t('settings.cli.submenu_hint')}[/dim]\n"
        )
        table = Table(show_header=True, header_style="bold")
        table.add_column("#", justify="right")
        table.add_column(_wizard_t("settings.cli.col_field"))
        table.add_column(_wizard_t("settings.cli.col_current"), overflow="fold")
        table.add_row("0", _wizard_t("settings.cli.back"), "")
        for i, name in enumerate(fields, start=1):
            val = getattr(s, name)
            table.add_row(str(i), name, _display_value(name, val))
        console.print(table)
        console.print(f"[bold]{_wizard_t('settings.cli.pick_field')}[/bold]: ", end="")
        sys.stdout.flush()
        try:
            choice = await _readline(console)
        except EOFError:
            return
        choice = choice.strip()
        if choice == "0" or choice == "":
            return
        if choice.lower() == "r":
            reload_settings()
            s = config_mod.settings
            console.print(f"[dim]{_wizard_t('settings.cli.reloaded')}[/dim]")
            continue
        try:
            num = int(choice)
        except ValueError:
            console.print(f"[red]{_wizard_t('settings.cli.enter_number')}[/red]")
            continue
        if num < 1 or num > len(fields):
            console.print(f"[red]{_wizard_t('settings.cli.invalid_index')}[/red]")
            continue

        fname = fields[num - 1]
        field_info = Settings.model_fields[fname]
        cur = getattr(s, fname)
        console.print(f"{_wizard_t('settings.cli.field_prefix')} [cyan]{fname}[/cyan]")
        console.print(
            f"{_wizard_t('settings.cli.type_prefix')}: [dim]{field_info.annotation}[/dim]"
        )
        console.print(f"{_wizard_t('settings.cli.current_prefix')}: {_display_value(fname, cur)}")
        if _is_secret_field(fname):
            console.print(f"[yellow]{_wizard_t('settings.cli.secret_local_only')}[/yellow]")
        if fname == "ADAMI_MCP_SERVERS_JSON":
            console.print(f"[dim]{_wizard_t('settings.cli.mcp_tpl_hint')}[/dim]")
        console.print(f"{_wizard_t('settings.cli.new_value_prompt')}: ", end="")
        sys.stdout.flush()
        try:
            raw = await _readline(console)
        except EOFError:
            return
        raw = raw.strip()
        if raw == "":
            console.print(f"[dim]{_wizard_t('settings.cli.cancelled')}[/dim]")
            continue
        if raw.lower() == "tpl" and fname == "ADAMI_MCP_SERVERS_JSON":
            console.print(f"\n[bold]{_wizard_t('settings.cli.mcp_tpl_title')}[/bold]")
            console.print(mcp_servers_json_template())
            console.print(f"[dim]{_wizard_t('settings.cli.mcp_tpl_footer')}[/dim]")
            continue
        if raw.lower() == "clear":
            write_cli_overrides({fname: None})
            reload_settings()
            s = config_mod.settings
            console.print(
                f"[green]{_wizard_t('settings.cli.override_removed', name=fname)}[/green]"
            )
            continue
        try:
            parsed = _coerce_value(fname, field_info.annotation, raw)
            stored = _format_stored_value(parsed)
            write_cli_overrides({fname: stored})
            reload_settings()
            s = config_mod.settings
            console.print(f"[green]{_wizard_t('settings.cli.saved_reload', name=fname)}[/green]")
        except ValueError as e:
            console.print(f"[red]{e}[/red]")
