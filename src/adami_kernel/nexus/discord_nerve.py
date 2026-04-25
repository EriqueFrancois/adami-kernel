# src/adami_kernel/nexus/discord_nerve.py
import asyncio
import base64
import logging
import os
import tempfile
from typing import Any, Dict, List, Optional

import discord
from discord.ext import commands
from discord.ui import Button, View

from adami_kernel.config import settings
from adami_kernel.core.restart_control import (
    cancel_process_restart,
    confirm_process_restart,
    discard_task_queue,
    request_process_restart_for_chat,
    resume_task_queue,
)
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.i18n.ui_static import (
    is_entry_menu_command,
    port_is_filler_reply_for_log,
    port_report_text_triggers,
    ui_t,
)
from adami_kernel.nexus.base_nerve import BaseNerve
from adami_kernel.nexus.chat_settings_wizard import (
    ChatSettingsState,
    categories_text,
    closed_settings_ack_text,
    entry_menu_discord_button_labels,
    handle_text,
    menu_text,
)
from adami_kernel.nexus.event import EventPriority
from adami_kernel.nexus.report_wizard_i18n import (
    immediate_report_intro,
    immediate_report_run_buttons,
    report_section_toggle_buttons,
    report_sections_intro,
    report_type_buttons,
    report_wizard_intro,
)
from adami_kernel.nexus.system_commands_catalog import markdown_reference
from adami_kernel.observability.messenger_metrics import record_notification_send

logger = logging.getLogger("AdamI-DiscordNerve")


class DiscordNerve(BaseNerve):
    """
    AdamI Discord 接入层（工业级最终版）
    - 完整事件发布 + 详细日志
    - 附件临时文件强保护
    - 全局异常处理器
    - 【本次核心修复】：任务失败回复拦截弱化 + 思考消息清理强化 + 详细诊断日志
    - 【阶段3 集成】：与 Telegram 完全一致的 DIGEST 审批流（digest:approve_all / reject_all）
    - 支持交互按钮（View + Button + custom_id）
    - 状态汇报方法
    """

    def __init__(self, publish_func):
        super().__init__(publish_func)

        self.token = settings.DISCORD_BOT_TOKEN
        if not self.token:
            logger.error(boot_t("boot.log.discord_no_token"))
            self.token = None
            return

        intents = discord.Intents.default()
        intents.message_content = True
        intents.messages = True
        intents.guilds = True
        intents.dm_messages = True
        intents.members = True

        self.bot = commands.Bot(command_prefix="!", intents=intents)
        self.last_chat_id = None
        self.last_channel = None
        self.default_channel_id = getattr(settings, "DISCORD_DEFAULT_CHANNEL_ID", None)
        self.default_guild_id = getattr(settings, "DISCORD_DEFAULT_GUILD_ID", None)
        self.default_user_id = getattr(settings, "DISCORD_DEFAULT_USER_ID", None)

        self._background_tasks = set()
        # channel_id -> mode: menu | prompt | settings
        self._entry_mode: Dict[str, str] = {}
        self._settings_state: Dict[str, ChatSettingsState] = {}
        self._menu_bootstrapped: set[str] = set()
        # report wizard state: channel_id -> dict
        self._report_wizard: Dict[str, Dict[str, Any]] = {}
        # on_ready 在重连时会多次触发：避免重复 tree.sync（限流）与重复推送入口菜单
        self._discord_slash_tree_synced: bool = False
        self._discord_on_ready_dm_sent: bool = False
        self._discord_logged_skip_menu_no_user: bool = False

        self._setup_events()
        from adami_kernel.nexus.discord_slash_setup import register_slash_commands

        register_slash_commands(self)
        logger.info(boot_t("boot.log.discord_init_ok"))

    @staticmethod
    def _locale_kw_from_message(message: discord.Message) -> Dict[str, str]:
        from adami_kernel.i18n.locale_resolve import hint_locale_from_discord_locale

        loc = getattr(message.author, "locale", None)
        h = hint_locale_from_discord_locale(loc)
        return {"locale": h} if h else {}

    @staticmethod
    def _locale_kw_from_interaction(interaction: discord.Interaction) -> Dict[str, str]:
        from adami_kernel.i18n.locale_resolve import hint_locale_from_discord_locale

        u = interaction.user
        loc = getattr(u, "locale", None) if u else None
        h = hint_locale_from_discord_locale(loc)
        return {"locale": h} if h else {}

    def _schedule_cleanup(self, file_path: str, delay: int = 180):
        """工业级延迟清理临时文件"""

        async def _cleanup_task():
            try:
                await asyncio.sleep(delay)
                if file_path and os.path.exists(file_path):
                    os.unlink(file_path)
                    logger.debug(boot_t("boot.log.discord_temp_recycled", path=file_path))
            except asyncio.CancelledError:
                if file_path and os.path.exists(file_path):
                    try:
                        os.unlink(file_path)
                    except:
                        pass
            except Exception as e:
                logger.warning(boot_t("boot.log.discord_temp_recycle_fail", detail=str(e)))

        task = asyncio.create_task(_cleanup_task())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    def _setup_events(self):
        @self.bot.event
        async def on_ready():
            logger.info(
                boot_t(
                    "boot.log.discord_login_ok",
                    user=self.bot.user,
                    user_id=self.bot.user.id,
                )
            )
            logger.info(boot_t("boot.log.discord_guilds_dm", guilds=len(self.bot.guilds)))
            await self.bot.change_presence(
                activity=discord.Game(ui_t("port.discord.presence_game"))
            )
            from adami_kernel.nexus.discord_slash_setup import sync_slash_command_tree

            if not self._discord_slash_tree_synced:
                if await sync_slash_command_tree(self):
                    self._discord_slash_tree_synced = True
            # 启动完成后主动推送“已启动 + 入口菜单”（仅首次 on_ready，重连不再刷）
            try:
                # 1) 优先 DM 默认用户（更符合“只发给我，不打扰频道”）
                if self.default_user_id and not self._discord_on_ready_dm_sent:
                    try:
                        user = self.bot.get_user(
                            int(self.default_user_id)
                        ) or await self.bot.fetch_user(int(self.default_user_id))
                        if user:
                            dm = user.dm_channel or await user.create_dm()
                            await dm.send(ui_t("port.boot.system_ready"))
                            self._menu_bootstrapped.add(str(dm.id))
                            self._menu_bootstrapped.add(f"user:{int(self.default_user_id)}")
                            self._discord_on_ready_dm_sent = True
                            return
                    except Exception as e:
                        logger.warning(boot_t("boot.log.discord_dm_push_fail", detail=str(e)))
                elif not self.default_user_id and not self._discord_logged_skip_menu_no_user:
                    self._discord_logged_skip_menu_no_user = True
                    logger.debug(boot_t("boot.log.discord_skip_menu_no_default_user"))
            except Exception as e:
                logger.warning(boot_t("boot.log.discord_startup_menu_fail", detail=str(e)))

        @self.bot.event
        async def on_message(message: discord.Message):
            if message.author.bot:
                return

            self.last_chat_id = str(message.channel.id)
            self.last_channel = message.channel

            content = message.content.strip() if message.content else ""
            channel_id = str(message.channel.id)
            mode = self._entry_mode.get(channel_id, "normal")
            user_key = f"user:{message.author.id}"
            has_content = bool(content)
            has_attachment = bool(message.attachments)

            # 必须在「首次 DM 补发菜单」之前处理：否则首条消息为 menu 时会推送两次入口菜单
            if has_content and is_entry_menu_command(content):
                self._menu_bootstrapped.add(user_key)
                self._entry_mode[channel_id] = "normal"
                self._settings_state.pop(channel_id, None)
                self._report_wizard.pop(channel_id, None)
                await self._send_entry_menu(channel_id)
                return

            # 双保险（DM 版）：首次收到消息时若未推送过菜单，则私信发给用户（不在频道发菜单）
            if user_key not in self._menu_bootstrapped:
                if self.default_user_id and str(message.author.id) != str(self.default_user_id):
                    # 限制只对默认用户推送（避免在公共服务器里给其他人发 DM）
                    self._menu_bootstrapped.add(user_key)
                else:
                    try:
                        dm = message.author.dm_channel or await message.author.create_dm()
                        await dm.send(ui_t("port.boot.system_ready"))
                    except Exception as e:
                        logger.warning(boot_t("boot.log.discord_first_dm_menu_fail", detail=str(e)))
                    self._menu_bootstrapped.add(user_key)

            if mode == "settings" and has_content:
                st = self._settings_state.get(channel_id) or ChatSettingsState(stage="category")
                st2, reply, _buttons = handle_text(st, content)
                self._settings_state[channel_id] = st2
                if getattr(st2, "start_report_wizard", False):
                    self._entry_mode[channel_id] = "normal"
                    self._settings_state.pop(channel_id, None)
                    await message.channel.send(reply[:1900])
                    stw = {
                        "stage": "choose_type",
                        "report_type": None,
                        "sections": {
                            "general_news": False,
                            "sports": False,
                            "politics": False,
                            "military": False,
                            "tech_news": False,
                        },
                    }
                    self._report_wizard[channel_id] = stw
                    await self.send_interactive_buttons(
                        channel_id,
                        report_wizard_intro(),
                        report_type_buttons(),
                    )
                    return
                if getattr(st2, "exit_to_main", False):
                    self._entry_mode[channel_id] = "normal"
                    self._settings_state.pop(channel_id, None)
                    await message.channel.send(closed_settings_ack_text())
                    await self._send_entry_menu(channel_id)
                    return
                await message.channel.send(reply[:1900])
                return

            # Report wizard entrypoint (text trigger)
            if mode == "normal" and has_content:
                norm = content.lower().strip()
                if norm in port_report_text_triggers():
                    st = {
                        "stage": "choose_type",
                        "report_type": None,
                        "sections": {
                            "general_news": False,
                            "sports": False,
                            "politics": False,
                            "military": False,
                            "tech_news": False,
                        },
                    }
                    self._report_wizard[channel_id] = st
                    await self.send_interactive_buttons(
                        channel_id,
                        report_wizard_intro(),
                        report_type_buttons(),
                    )
                    return

            # Report wizard schedule input (normal mode only)
            if mode == "normal" and has_content:
                st = self._report_wizard.get(channel_id)
                if st and st.get("stage") == "await_schedule":
                    parts = content.split()
                    if len(parts) >= 2:
                        tz = parts[0].strip()
                        hhmm = parts[1].strip()
                        rt = st.get("report_type") or "daily"
                        updates = {
                            "schedule": {"timezone": tz, "publish_time_hhmm": hhmm},
                            "sections": dict(st.get("sections") or {}),
                        }
                        import json

                        ev = self.create_event(
                            task=f"/report set {rt} {json.dumps(updates, ensure_ascii=False)}",
                            platform="discord",
                            priority=EventPriority.HIGH,
                            chat_id=str(message.channel.id),
                            raw_content=content,
                            **self._locale_kw_from_message(message),
                        )
                        try:
                            await self.publish(ev)
                            self._report_wizard.pop(channel_id, None)
                            await message.channel.send(
                                ui_t("port.report.schedule_submitted", rtype=rt, tz=tz, hhmm=hhmm)
                            )
                        except Exception as e:
                            logger.error(
                                "[Discord] report wizard publish failed: %s", e, exc_info=True
                            )
                            await message.channel.send(
                                ui_t("port.report.discord_submit_failed", detail=str(e))
                            )
                        return
                    await message.channel.send(ui_t("port.report.schedule_bad_format"))
                    return

            if has_content or has_attachment:
                # 【修复】：剥除 [Discord消息] 前缀，保持 Prompt 纯净
                task = content if content else ui_t("port.discord.attachment_placeholder")
                event = self.create_event(
                    task=task,
                    platform="discord",
                    priority=EventPriority.HIGH,
                    chat_id=str(message.channel.id),
                    discord_channel_id=str(message.channel.id),
                    discord_author=message.author.name,
                    is_dm=isinstance(message.channel, discord.DMChannel),
                    raw_content=content,
                    **self._locale_kw_from_message(message),
                )
                try:
                    await self.publish(event)
                    att_ph = ui_t("port.discord.attachment_placeholder")
                    preview = content[:80] if content else att_ph
                    logger.info(
                        boot_t(
                            "boot.log.discord_event_published",
                            preview=preview,
                            n=str(len(message.attachments)),
                        )
                    )
                except Exception as e:
                    logger.error(
                        boot_t("boot.log.discord_event_publish_fail", detail=str(e)), exc_info=True
                    )
            else:
                logger.debug(boot_t("boot.log.discord_empty_message"))

            if message.attachments:
                for attachment in message.attachments:
                    await self._handle_attachment(message, attachment)

        @self.bot.event
        async def on_interaction(interaction: discord.Interaction):
            """阶段3 核心：处理 DIGEST 按钮回调（与 Telegram 完全一致）"""
            if interaction.data and interaction.data.get("custom_id", "").startswith("digest:"):
                await self._handle_digest_callback(interaction)
                return
            # 入口菜单 / 系统设置回调
            try:
                cid = (interaction.data or {}).get("custom_id", "")
            except Exception:
                cid = ""
            if isinstance(cid, str) and cid.startswith("menu:"):
                await self._handle_menu_callback(interaction)
                return
            if isinstance(cid, str) and cid.startswith("report:"):
                await self._handle_report_callback(interaction)
                return
            if isinstance(cid, str) and (cid.startswith("restart:") or cid.startswith("queue:")):
                await self._handle_restart_or_queue_callback(interaction)
                return

        @self.bot.event
        async def on_command_error(ctx, error):
            if isinstance(error, commands.CommandNotFound):
                return
            logger.error(boot_t("boot.log.discord_command_error", detail=str(error)), exc_info=True)

    # ====================== 【阶段3 新增】DIGEST 按钮回调处理 ======================
    async def _handle_digest_callback(self, interaction: discord.Interaction):
        """Discord 版 digest 回调（逻辑与 Telegram 完全一致）"""
        data = interaction.data["custom_id"]
        action = data.split(":")[1]
        cand_path = settings.path_brain_candidates_md
        profile_path = settings.path_brain_profile_md
        digest_stub = ui_t("port.digest.candidates_md_stub")

        try:
            if action == "approve_all":
                with open(cand_path, "r", encoding="utf-8") as f:
                    cands = [line for line in f.read().splitlines() if line.startswith("- 🟢")]

                if cands:
                    with open(profile_path, "a", encoding="utf-8") as f:
                        # 写入正式档案，去掉 🟢 标志
                        f.write("\n" + "\n".join(cands).replace("- 🟢", "- ") + "\n")

                # 清空候选池内容，只留标题
                with open(cand_path, "w", encoding="utf-8") as f:
                    f.write(digest_stub)

                await interaction.response.edit_message(
                    content=ui_t("port.digest.approved_message")
                )

            elif action == "reject_all":
                with open(cand_path, "w", encoding="utf-8") as f:
                    f.write(digest_stub)
                await interaction.response.edit_message(
                    content=ui_t("port.digest.rejected_message")
                )
        except Exception as e:
            logger.error(boot_t("boot.log.discord_digest_cb_fail", detail=str(e)))
            await interaction.response.edit_message(
                content=ui_t("port.discord.digest_edit_error", detail=str(e))
            )

    # =================================================================================

    async def _handle_menu_callback(self, interaction: discord.Interaction) -> None:
        data = (interaction.data or {}).get("custom_id", "")
        action = data.split(":", 1)[1]
        channel_id = str(interaction.channel_id)
        if action == "normal":
            self._entry_mode[channel_id] = "normal"
            try:
                await interaction.response.edit_message(
                    content=ui_t("port.callback.normal_message"), view=None
                )
            except Exception:
                await interaction.response.send_message(
                    ui_t("port.callback.normal_message"), ephemeral=True
                )
            return
        if action == "settings":
            self._entry_mode[channel_id] = "settings"
            self._settings_state[channel_id] = ChatSettingsState(stage="category")
            try:
                await interaction.response.edit_message(
                    content=categories_text(), view=self._settings_close_view()
                )
            except Exception:
                await interaction.response.send_message(categories_text(), ephemeral=True)
            return
        if action == "restart":
            ok = request_process_restart_for_chat(channel_id, platform="discord")
            msg = ui_t("port.menu.restart_ack") if ok else ui_t("port.menu.restart_pending_prompt")
            try:
                if ok:
                    await interaction.response.send_message(msg, ephemeral=True)
                    return
                view = View(timeout=None)
                view.add_item(
                    Button(
                        label=ui_t("port.menu.restart_pending_btn_confirm"),
                        style=discord.ButtonStyle.danger,
                        custom_id="restart:confirm",
                    )
                )
                view.add_item(
                    Button(
                        label=ui_t("port.menu.restart_pending_btn_cancel"),
                        style=discord.ButtonStyle.secondary,
                        custom_id="restart:cancel",
                    )
                )
                await interaction.response.send_message(msg, view=view, ephemeral=True)
            except Exception as e:
                logger.warning(
                    boot_t("boot.log.discord_entry_menu_fail", detail=f"restart_ack: {e}")
                )
            return
        if action == "report":
            try:
                await interaction.response.send_message(
                    ui_t("port.report.immediate_menu_hint"), ephemeral=True
                )
            except Exception as e:
                logger.warning(
                    boot_t("boot.log.discord_entry_menu_fail", detail=f"report_menu: {e}")
                )
            await self.send_interactive_buttons(
                channel_id, immediate_report_intro(), immediate_report_run_buttons()
            )
            return
        if action == "close_settings":
            self._entry_mode[channel_id] = "normal"
            self._settings_state.pop(channel_id, None)
            try:
                await interaction.response.edit_message(
                    content=ui_t("port.callback.close_message"), view=None
                )
            except Exception:
                await interaction.response.send_message(
                    ui_t("port.callback.close_message"), ephemeral=True
                )
            return

    async def _handle_restart_or_queue_callback(self, interaction: discord.Interaction) -> None:
        data = (interaction.data or {}).get("custom_id", "")
        channel_id = str(interaction.channel_id)
        if data == "restart:confirm":
            ok = confirm_process_restart(channel_id, platform="discord")
            msg = ui_t("port.menu.restart_ack") if ok else ui_t("port.menu.restart_unavailable")
            try:
                await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass
            return
        if data == "restart:cancel":
            cancel_process_restart(channel_id)
            try:
                await interaction.response.send_message(
                    ui_t("port.callback.close_message"), ephemeral=True
                )
            except Exception:
                pass
            return
        if data == "queue:resume":
            resume_task_queue(channel_id, platform="discord")
            try:
                await interaction.response.send_message(
                    ui_t("shell.queue.resuming"), ephemeral=True
                )
            except Exception:
                pass
            return
        if data == "queue:discard":
            discard_task_queue(channel_id, platform="discord")
            try:
                await interaction.response.send_message(
                    ui_t("shell.queue.discarded"), ephemeral=True
                )
            except Exception:
                pass
            return

    def _entry_menu_view(self) -> View:
        a, b, c, d = entry_menu_discord_button_labels()
        view = View(timeout=None)
        view.add_item(Button(label=a, style=discord.ButtonStyle.success, custom_id="menu:normal"))
        view.add_item(Button(label=b, style=discord.ButtonStyle.primary, custom_id="menu:settings"))
        view.add_item(Button(label=c, style=discord.ButtonStyle.danger, custom_id="menu:restart"))
        view.add_item(Button(label=d, style=discord.ButtonStyle.secondary, custom_id="menu:report"))
        return view

    def _settings_close_view(self) -> View:
        view = View(timeout=None)
        view.add_item(
            Button(
                label=ui_t("port.menu.close_settings_btn"),
                style=discord.ButtonStyle.danger,
                custom_id="menu:close_settings",
            )
        )
        return view

    async def _send_entry_menu(self, channel_id: str) -> None:
        self._entry_mode[channel_id] = "normal"
        try:
            channel = self.bot.get_channel(int(channel_id)) or await self.bot.fetch_channel(
                int(channel_id)
            )
            if not channel:
                return
            await channel.send(menu_text(), view=self._entry_menu_view())
        except Exception as e:
            logger.warning(boot_t("boot.log.discord_entry_menu_fail", detail=str(e)))

    async def _slash_menu(self, interaction: discord.Interaction) -> None:
        channel_id = str(interaction.channel_id)
        self.last_chat_id = channel_id
        self.last_channel = interaction.channel
        if interaction.user:
            self._menu_bootstrapped.add(f"user:{interaction.user.id}")
        self._entry_mode[channel_id] = "normal"
        self._settings_state.pop(channel_id, None)
        self._report_wizard.pop(channel_id, None)
        try:
            await interaction.response.send_message(menu_text(), view=self._entry_menu_view())
        except Exception as e:
            logger.warning(boot_t("boot.log.discord_slash_menu_fail", detail=str(e)))

    async def _slash_adamih(self, interaction: discord.Interaction) -> None:
        loc = settings.effective_ui_default_locale()
        body = markdown_reference(loc)
        if len(body) > 1900:
            body = body[:1897] + "…"
        try:
            await interaction.response.send_message(body, ephemeral=True)
        except Exception as e:
            logger.warning(boot_t("boot.log.discord_slash_adamih_fail", detail=str(e)))

    async def _slash_forward(self, interaction: discord.Interaction, task: str) -> None:
        channel_id = str(interaction.channel_id)
        self.last_chat_id = channel_id
        self.last_channel = interaction.channel
        ch = interaction.channel
        is_dm = isinstance(ch, discord.DMChannel) if ch else False
        author = interaction.user.name if interaction.user else ""
        try:
            await interaction.response.send_message(ui_t("port.slash.queued"), ephemeral=True)
        except Exception:
            try:
                await interaction.response.defer(ephemeral=True)
            except Exception:
                pass
        ev = self.create_event(
            task=task,
            platform="discord",
            priority=EventPriority.HIGH,
            chat_id=channel_id,
            discord_channel_id=channel_id,
            discord_author=author,
            is_dm=is_dm,
            raw_content=task,
            **self._locale_kw_from_interaction(interaction),
        )
        try:
            await self.publish(ev)
        except Exception as e:
            logger.error(
                boot_t("boot.log.discord_slash_publish_fail", detail=str(e)), exc_info=True
            )

    async def _handle_attachment(self, message: discord.Message, attachment: discord.Attachment):
        tmp_path = None
        try:
            filename = attachment.filename or "unknown"
            lower_name = filename.lower()
            content_type = attachment.content_type or ""

            if content_type.startswith("image/"):
                media_type = "photo"
                file_data = await attachment.read()
                b64 = base64.b64encode(file_data).decode("utf-8")
                extra = {"image_base64": b64, "file_name": filename}
                raw_data = b64

            elif content_type.startswith("audio/") or lower_name.endswith(
                (".ogg", ".mp3", ".wav", ".m4a", ".opus")
            ):
                media_type = "voice"
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=os.path.splitext(filename)[1]
                ) as tmp:
                    tmp_path = tmp.name
                await attachment.save(tmp_path)
                extra = {"file_path": tmp_path}
                raw_data = tmp_path

            else:
                media_type = "document"
                with tempfile.NamedTemporaryFile(
                    delete=False, suffix=os.path.splitext(filename)[1]
                ) as tmp:
                    tmp_path = tmp.name
                await attachment.save(tmp_path)
                extra = {"file_path": tmp_path, "file_name": filename}
                raw_data = tmp_path

            event = await self.media_to_event(
                media_type=media_type,
                raw_data=raw_data,
                chat_id=str(message.channel.id),
                extra={"discord_channel_id": str(message.channel.id), **extra},
            )

            await self.publish(event)
            logger.info(
                boot_t(
                    "boot.log.discord_attachment_published",
                    name=filename,
                    media_type=str(media_type),
                )
            )

            if tmp_path:
                self._schedule_cleanup(tmp_path, delay=180)

        except Exception as e:
            logger.error(boot_t("boot.log.discord_attachment_fail", detail=str(e)), exc_info=True)
            if tmp_path and os.path.exists(tmp_path):
                try:
                    os.unlink(tmp_path)
                except:
                    pass

    # ====================== 【阶段3 新增】Discord 交互按钮发送 ======================
    async def send_interactive_buttons(
        self, channel_id: str, text: str, buttons: List[Dict]
    ) -> bool:
        """Discord 版 send_interactive_buttons（与 Telegram 逻辑完全一致）。"""
        if not self.bot or not self.bot.is_ready():
            logger.warning(boot_t("boot.log.discord_buttons_not_ready"))
            record_notification_send("discord", "send_interactive", "skipped")
            return False

        try:
            channel = self.bot.get_channel(int(channel_id)) or await self.bot.fetch_channel(
                int(channel_id)
            )
            if not channel:
                logger.error(
                    boot_t("boot.log.discord_channel_not_found", channel_id=str(channel_id))
                )
                record_notification_send("discord", "send_interactive", "failure")
                return False

            view = View(timeout=None)

            for btn in buttons:
                style = (
                    discord.ButtonStyle.success
                    if "approve" in btn["callback_data"]
                    else discord.ButtonStyle.danger
                )
                button = Button(label=btn["text"], style=style, custom_id=btn["callback_data"])
                view.add_item(button)

            await channel.send(text, view=view)
            logger.info(boot_t("boot.log.discord_hitl_buttons", channel_id=channel_id))
            record_notification_send("discord", "send_interactive", "success")
            return True
        except Exception as e:
            logger.error(boot_t("boot.log.discord_buttons_send_fail", detail=str(e)))
            record_notification_send("discord", "send_interactive", "failure")
            return False

    # =================================================================================

    async def _handle_report_callback(self, interaction: discord.Interaction) -> None:
        cid = (interaction.data or {}).get("custom_id", "")
        channel_id = str(interaction.channel_id)
        action = cid.split(":", 1)[1] if ":" in cid else ""
        st = self._report_wizard.get(channel_id) or {
            "stage": "choose_type",
            "report_type": None,
            "sections": {
                "general_news": False,
                "sports": False,
                "politics": False,
                "military": False,
                "tech_news": False,
            },
        }

        async def _send(text: str, buttons: List[Dict[str, str]]):
            await self.send_interactive_buttons(channel_id, text, buttons)

        if action.startswith("now:"):
            rt = action.split(":", 1)[1]
            if rt not in ("daily", "weekly", "monthly"):
                try:
                    await interaction.response.send_message(
                        ui_t("dp.report.err_bad_type"), ephemeral=True
                    )
                except Exception:
                    pass
                return
            try:
                await interaction.response.send_message(
                    ui_t("port.report.immediate_queued", rtype=rt), ephemeral=True
                )
            except Exception:
                try:
                    await interaction.response.defer(ephemeral=True)
                except Exception:
                    pass
            ch = interaction.channel
            is_dm = isinstance(ch, discord.DMChannel) if ch else False
            author = interaction.user.name if interaction.user else ""
            ev = self.create_event(
                task=f"/report run {rt}",
                platform="discord",
                priority=EventPriority.HIGH,
                chat_id=channel_id,
                discord_channel_id=channel_id,
                discord_author=author,
                is_dm=is_dm,
                raw_content=f"/report run {rt}",
                **self._locale_kw_from_interaction(interaction),
            )
            await self.publish(ev)
            return

        if action in ("open", "start"):
            st["stage"] = "choose_type"
            self._report_wizard[channel_id] = st
            try:
                await interaction.response.send_message(
                    ui_t("port.report.discord_started_ephemeral"), ephemeral=True
                )
            except Exception:
                pass
            await _send(report_wizard_intro(), report_type_buttons())
            return

        if action == "cancel":
            self._report_wizard.pop(channel_id, None)
            try:
                await interaction.response.send_message(
                    ui_t("port.report.cancel_message"), ephemeral=True
                )
            except Exception:
                pass
            return

        if action.startswith("type:"):
            rt = action.split(":", 1)[1]
            st["report_type"] = rt
            st["stage"] = "choose_sections"
            self._report_wizard[channel_id] = st
            sec = st["sections"]
            await _send(report_sections_intro(rt), report_section_toggle_buttons(sec))
            try:
                await interaction.response.send_message(
                    ui_t("port.report.discord_type_selected_ephemeral"), ephemeral=True
                )
            except Exception:
                pass
            return

        if action.startswith("toggle:"):
            key = action.split(":", 1)[1]
            if key in st["sections"]:
                st["sections"][key] = not bool(st["sections"][key])
            self._report_wizard[channel_id] = st
            rt = st.get("report_type") or "daily"
            sec = st["sections"]
            await _send(report_sections_intro(rt), report_section_toggle_buttons(sec))
            try:
                await interaction.response.send_message(
                    ui_t("port.report.discord_toggle_updated_ephemeral"), ephemeral=True
                )
            except Exception:
                pass
            return

        if action == "next_schedule":
            st["stage"] = "await_schedule"
            self._report_wizard[channel_id] = st
            try:
                await interaction.response.send_message(
                    ui_t("port.report.schedule_body_discord"),
                    ephemeral=True,
                )
            except Exception:
                pass
            return

    async def update_ui_thought(self, channel_id: str, thought: Any):
        """Discord：禁用思考流刷屏（只用最终回复）。"""
        return

    async def send_message(
        self,
        channel_id: Optional[str] = None,
        content: str = "",
        channel: Optional[discord.TextChannel] = None,
    ) -> bool:
        """【核心修复】任务失败回复必达 + 弱化拦截 + 详细日志"""
        if not self.bot or not self.bot.is_ready():
            logger.warning(boot_t("boot.log.discord_send_not_ready"))
            record_notification_send("discord", "send_message", "skipped")
            return False

        target_channel = channel or self.last_channel
        if not target_channel and channel_id:
            try:
                cid = int(channel_id)
                target_channel = self.bot.get_channel(cid) or await self.bot.fetch_channel(cid)
            except Exception as e:
                logger.error(
                    boot_t("boot.log.discord_resolve_channel_fail", detail=str(e)), exc_info=True
                )

        if not target_channel:
            logger.error(boot_t("boot.log.discord_no_target_channel"))
            record_notification_send("discord", "send_message", "failure")
            return False

        # 【核心修复】弱化拦截：仅记录警告，始终发送最终回复
        if port_is_filler_reply_for_log(content):
            logger.warning(boot_t("boot.log.discord_filler_reply", preview=content[:100]))

        try:
            await target_channel.send(content[:2000])
            logger.info(
                boot_t(
                    "boot.log.discord_final_sent",
                    channel_id=str(channel_id or "last_channel"),
                    length=str(len(content)),
                    preview=content[:120],
                )
            )
            record_notification_send("discord", "send_message", "success")
            return True
        except Exception as e:
            logger.error(boot_t("boot.log.discord_final_send_fail", detail=str(e)), exc_info=True)
            record_notification_send("discord", "send_message", "failure")
            return False

    async def start_listening(self):
        if not self.token:
            logger.warning(boot_t("boot.log.discord_token_empty"))
            return
        self._running = True
        logger.info(boot_t("boot.log.discord_bot_starting"))
        try:
            await self.bot.start(self.token)
        except Exception as e:
            logger.error(boot_t("boot.log.discord_start_fail", detail=str(e)), exc_info=True)
            self._running = False

    async def stop(self):
        logger.info(boot_t("boot.log.discord_shutdown"))
        for task in list(self._background_tasks):
            if not task.done():
                task.cancel()
        if self.bot:
            try:
                await self.bot.close()
                logger.info(boot_t("boot.log.discord_closed"))
            except Exception as e:
                logger.warning(boot_t("boot.log.discord_close_warn", detail=str(e)))
        self._background_tasks.clear()
        await super().stop()

    async def get_status(self) -> dict:
        return {
            "running": getattr(self, "_running", False),
            "bot_ready": self.bot.is_ready() if self.bot else False,
            "user": str(self.bot.user) if self.bot and self.bot.user else None,
        }


# End of src/adami_kernel/nexus/discord_nerve.py
