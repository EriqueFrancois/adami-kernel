"""Register Discord Application Commands (slash) mirroring ``system_commands_manifest``."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

import discord
from discord import app_commands

from adami_kernel.config import settings
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.nexus.system_commands_catalog import discord_slash_specs

if TYPE_CHECKING:
    from adami_kernel.nexus.discord_nerve import DiscordNerve

logger = logging.getLogger("AdamI-DiscordSlash")


def register_slash_commands(nerve: "DiscordNerve") -> None:
    """Attach slash commands to ``nerve.bot.tree`` (call once before ``bot.start``)."""
    tree = nerve.bot.tree

    def _d(name: str) -> str:
        for s in discord_slash_specs(settings.effective_ui_default_locale()):
            if s["name"] == name:
                return str(s["description"])[:100]
        return name[:100]

    @tree.command(name="menu", description=_d("menu"))
    async def slash_menu(interaction: Any) -> None:
        await nerve._slash_menu(interaction)

    @tree.command(name="adamih", description=_d("adamih"))
    async def slash_adamih(interaction: Any) -> None:
        await nerve._slash_adamih(interaction)

    @tree.command(name="report", description=_d("report"))
    @app_commands.describe(args="e.g. help | list | run daily")
    async def slash_report(interaction: Any, args: str = "help") -> None:
        await nerve._slash_forward(interaction, f"/report {args}".strip())

    @tree.command(name="maintain", description=_d("maintain"))
    async def slash_maintain(interaction: Any) -> None:
        await nerve._slash_forward(interaction, "/maintain")

    @tree.command(name="digest", description=_d("digest"))
    async def slash_digest(interaction: Any) -> None:
        await nerve._slash_forward(interaction, "/digest")

    @tree.command(name="intake", description=_d("intake"))
    async def slash_intake(interaction: Any) -> None:
        await nerve._slash_forward(interaction, "/intake")

    @tree.command(name="writing", description=_d("writing"))
    @app_commands.describe(content="Optional instruction body")
    async def slash_writing(interaction: Any, content: str = "") -> None:
        t = "/writing" if not (content or "").strip() else f"/writing {content.strip()}"
        await nerve._slash_forward(interaction, t)

    @tree.command(name="task", description=_d("task"))
    @app_commands.describe(text="Task line to append")
    async def slash_task(interaction: Any, text: str) -> None:
        await nerve._slash_forward(interaction, f"/task {text}".strip())

    @tree.command(name="todo", description=_d("todo"))
    @app_commands.describe(text="Todo line to append")
    async def slash_todo(interaction: Any, text: str) -> None:
        await nerve._slash_forward(interaction, f"/todo {text}".strip())

    @tree.command(name="force_optimize", description=_d("force_optimize"))
    @app_commands.describe(skill="Skill name, e.g. WEATHER_QUERY")
    async def slash_force_optimize(interaction: Any, skill: str) -> None:
        await nerve._slash_forward(interaction, f"/force_optimize {skill.strip().upper()}".strip())

    @tree.command(name="optimize", description=_d("optimize"))
    @app_commands.describe(skill="Skill name, e.g. WEATHER_QUERY")
    async def slash_optimize(interaction: Any, skill: str) -> None:
        await nerve._slash_forward(interaction, f"/optimize {skill.strip().upper()}".strip())

    @tree.command(name="status", description=_d("status"))
    async def slash_status(interaction: Any) -> None:
        await nerve._slash_forward(interaction, "/status")


async def sync_slash_command_tree(nerve: "DiscordNerve") -> bool:
    """Call from ``on_ready`` after the bot is connected.

    Guild-only commands (``tree.sync(guild=…)``) do **not** appear in DMs or other
    servers. Use global sync by default so ``/`` works like Telegram; optional
    ``DISCORD_SLASH_GUILD_ID`` keeps a fast guild-scoped dev path.

    Returns ``True`` if sync completed without error (caller may mark one-shot done).
    """
    try:
        raw = getattr(settings, "DISCORD_SLASH_GUILD_ID", None)
        gid = str(raw).strip() if raw is not None else ""
        if gid:
            g = discord.Object(id=int(gid))
            await nerve.bot.tree.sync(guild=g)
            logger.debug(boot_t("boot.log.discord_slash_synced_guild", guild_id=str(gid)))
        else:
            await nerve.bot.tree.sync()
            logger.debug(boot_t("boot.log.discord_slash_synced_global"))
        return True
    except Exception as e:
        logger.debug(boot_t("boot.log.discord_slash_sync_fail", detail=str(e)))
        return False
