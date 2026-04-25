# src/adami_kernel/nexus/telegram_sensory.py
import asyncio
import base64
import logging
import os
import tempfile
from io import BytesIO
from typing import Any, Dict, List

from aiogram import Bot, Dispatcher, types
from aiogram.types import BotCommand, CallbackQuery, ContentType

try:
    # aiogram v3
    from aiogram.exceptions import TelegramConflictError
except Exception:  # pragma: no cover
    TelegramConflictError = None  # type: ignore

import aiofiles
import aiohttp

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
    entry_menu_telegram_buttons,
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
from adami_kernel.nexus.telegram_inline_markup import inline_keyboard_one_button_per_row
from adami_kernel.observability.messenger_metrics import (
    record_notification_retry,
    record_notification_send,
)
from adami_kernel.orchestrator.hitl_handler import hitl_handler

logger = logging.getLogger("AdamI-TelegramSensory")


class TelegramSensory(BaseNerve):
    """
    AdamI Telegram 接入层（工业级最终版）
    - 统一类名 TelegramSensory（修复注册中心导入）
    - 继承 BaseNerve（获得 create_event / media_to_event / publish）
    - 完整媒体处理 + HITL 按钮支持
    - 【本次核心修复】：思考消息强制清理 + 回复拦截弱化 + 详细诊断日志
    - 【阶段3 集成】：新增 digest:approve_all / digest:reject_all 按钮回调处理
    - 强引用后台任务 + 优雅停止
    """

    def __init__(self, publish_func):
        super().__init__(publish_func)

        self.token = settings.TELEGRAM_BOT_TOKEN
        raw_default = getattr(settings, "TELEGRAM_CHAT_ID", None)
        self.default_chat_id = int(raw_default or 0)
        self.openai_api_key = settings.OPENAI_API_KEY

        self.bot = None
        self.dp = None
        self.active_status = {}
        self.last_chat_id = self.default_chat_id

        self._background_tasks = set()
        self._polling_lock_fd = None
        # chat_id -> mode: menu | prompt | settings
        self._entry_mode: Dict[str, str] = {}
        self._settings_state: Dict[str, ChatSettingsState] = {}
        self._menu_bootstrapped: set[str] = set()
        # report wizard state: chat_id -> dict
        self._report_wizard: Dict[str, Dict[str, Any]] = {}

        logger.info(boot_t("boot.log.telegram_init_ok"))

    @staticmethod
    def _locale_kw_from_message(message: types.Message) -> Dict[str, str]:
        from adami_kernel.i18n.locale_resolve import hint_locale_from_telegram_language_code

        u = getattr(message, "from_user", None)
        code = getattr(u, "language_code", None) if u else None
        h = hint_locale_from_telegram_language_code(code)
        return {"locale": h} if h else {}

    def _try_acquire_polling_lock(self) -> bool:
        """
        防止重复 getUpdates 轮询导致 TelegramConflictError 刷屏。
        使用本机文件锁（同一台机器/同一 workspace 内只允许一个 polling 实例）。
        """
        lock_dir = str(settings.adami_data_dir_path)
        os.makedirs(lock_dir, exist_ok=True)
        lock_path = os.path.join(lock_dir, "telegram_polling.lock")
        try:
            import fcntl  # POSIX only (macOS/Linux)

            fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                os.close(fd)
                return False
            self._polling_lock_fd = fd
            return True
        except Exception as e:
            # 若锁不可用，不要阻断启动；但会失去“单实例”保护
            logger.warning(boot_t("boot.log.telegram_polling_lock_unavailable", detail=str(e)))
            return True

    def _schedule_cleanup(self, file_path: str, delay: int = 180):
        """工业级延迟清理临时文件"""

        async def _cleanup_task():
            try:
                await asyncio.sleep(delay)
                if file_path and os.path.exists(file_path):
                    os.unlink(file_path)
                    logger.debug(boot_t("boot.log.telegram_temp_recycled", path=file_path))
            except asyncio.CancelledError:
                if file_path and os.path.exists(file_path):
                    try:
                        os.unlink(file_path)
                    except:
                        pass
            except Exception as e:
                logger.warning(boot_t("boot.log.telegram_temp_recycle_fail", detail=str(e)))

        task = asyncio.create_task(_cleanup_task())
        self._background_tasks.add(task)
        task.add_done_callback(self._background_tasks.discard)

    async def _sync_telegram_bot_commands(self) -> None:
        """Publish command hints for Telegram’s “/” autocomplete (setMyCommands)."""
        if not self.bot:
            return
        try:
            from adami_kernel.nexus.system_commands_catalog import telegram_command_entries

            rows = telegram_command_entries(settings.effective_ui_default_locale())
            cmds = [BotCommand(command=n, description=(d or "AdamI")[:256]) for n, d in rows]
            await self.bot.set_my_commands(cmds)
            logger.info(boot_t("boot.log.telegram_commands_synced", count=str(len(cmds))))
        except Exception as e:
            logger.warning(boot_t("boot.log.telegram_commands_sync_fail", detail=str(e)))

    async def start_listening(self):
        if not self.token:
            logger.warning(boot_t("boot.log.telegram_no_token"))
            return

        self.bot = Bot(token=self.token)
        await self._sync_telegram_bot_commands()
        self.dp = Dispatcher()

        # 启动完成后主动推送“已启动 + 入口菜单”
        if self.default_chat_id:
            try:
                await self.bot.send_message(self.default_chat_id, ui_t("port.boot.system_ready"))
                self._menu_bootstrapped.add(str(self.default_chat_id))
            except Exception as e:
                logger.warning(boot_t("boot.log.telegram_startup_menu_fail", detail=str(e)))

        # polling 锁：用于避免 getUpdates 冲突；即使无法 polling，也尽量先完成启动菜单推送
        if not self._try_acquire_polling_lock():
            logger.warning(boot_t("boot.log.telegram_polling_singleton_skip"))
            return

        @self.dp.message()
        async def handle_all_media(message: types.Message):
            await self._handle_media(message)

        @self.dp.callback_query()
        async def handle_callback(callback: CallbackQuery):
            await self._handle_callback(callback)

        for attempt in range(3):
            try:
                await self.dp.start_polling(self.bot)
                logger.info(boot_t("boot.log.telegram_polling_started"))
                break
            except Exception as e:
                # Telegram 明确冲突：通常意味着同一个 bot token 在别处也在 getUpdates
                if TelegramConflictError is not None and isinstance(e, TelegramConflictError):
                    logger.error(boot_t("boot.log.telegram_conflict_stop"))
                    return
                logger.warning(
                    boot_t(
                        "boot.log.telegram_polling_attempt_fail",
                        attempt=attempt + 1,
                        detail=str(e),
                    )
                )
                if attempt == 2:
                    logger.error(boot_t("boot.log.telegram_polling_final_fail"))
                await asyncio.sleep(5)

    async def _handle_media(self, message: types.Message):
        self.last_chat_id = message.chat.id
        content_type = message.content_type

        logger.info(
            boot_t(
                "boot.log.telegram_inbound",
                ctype=str(content_type),
                chat_id=str(message.chat.id),
            )
        )

        # 双保险：若启动主动推送未命中，则在首次收到消息时补发入口菜单一次
        chat_id_s = str(message.chat.id)
        if chat_id_s not in self._menu_bootstrapped:
            try:
                await self.bot.send_message(message.chat.id, ui_t("port.boot.system_ready"))
            except Exception as e:
                logger.warning(boot_t("boot.log.telegram_first_menu_fail", detail=str(e)))
            self._menu_bootstrapped.add(chat_id_s)

        # 立即发送 typing + 思考中消息
        try:
            await self.bot.send_chat_action(chat_id=message.chat.id, action="typing")
            status_msg = await message.answer(ui_t("port.thinking.multimodal"))
            self.active_status[message.chat.id] = status_msg.message_id
        except Exception as e:
            logger.error(boot_t("boot.log.telegram_initial_thought_fail", detail=str(e)))

        if content_type == ContentType.TEXT:
            await self._handle_text(message)
        elif content_type == ContentType.VOICE:
            await self._handle_voice(message)
        elif content_type in (ContentType.PHOTO, ContentType.VIDEO, ContentType.VIDEO_NOTE):
            await self._handle_visual(message)
        elif content_type == ContentType.DOCUMENT:
            await self._handle_document(message)
        else:
            logger.warning(boot_t("boot.log.telegram_unsupported_media", ctype=str(content_type)))
            await message.answer(ui_t("port.media.unsupported", ctype=str(content_type)))

    async def _handle_callback(self, callback: CallbackQuery):
        data = callback.data

        # === 入口菜单：normal/settings/close ===
        if data and data.startswith("menu:"):
            chat_id = (
                str(callback.message.chat.id) if callback.message else str(callback.from_user.id)
            )
            action = data.split(":", 1)[1]
            if action == "normal":
                self._entry_mode[chat_id] = "normal"
                await self.bot.answer_callback_query(
                    callback.id, text=ui_t("port.callback.normal_answer")
                )
                await self.bot.send_message(int(chat_id), ui_t("port.callback.normal_message"))
                return
            if action == "settings":
                self._entry_mode[chat_id] = "settings"
                self._settings_state[chat_id] = ChatSettingsState(stage="category")
                await self.bot.answer_callback_query(
                    callback.id, text=ui_t("port.callback.settings_answer")
                )
                await self.bot.send_message(int(chat_id), categories_text())
                return
            if action == "restart":
                ok = request_process_restart_for_chat(chat_id, platform="telegram")
                await self.bot.answer_callback_query(
                    callback.id, text=ui_t("port.menu.restart_toast")
                )
                if ok:
                    await self.bot.send_message(int(chat_id), ui_t("port.menu.restart_ack"))
                else:
                    # If restart is gated by pending tasks, send confirmation buttons.
                    await self.send_interactive_buttons(
                        int(chat_id),
                        ui_t("port.menu.restart_pending_prompt"),
                        [
                            {
                                "text": ui_t("port.menu.restart_pending_btn_confirm"),
                                "callback_data": "restart:confirm",
                            },
                            {
                                "text": ui_t("port.menu.restart_pending_btn_cancel"),
                                "callback_data": "restart:cancel",
                            },
                        ],
                    )
                return
            if action == "report":
                await self.bot.answer_callback_query(
                    callback.id, text=ui_t("port.report.immediate_menu_toast")
                )
                await self.send_interactive_buttons(
                    int(chat_id), immediate_report_intro(), immediate_report_run_buttons()
                )
                return
            if action == "close_settings":
                self._entry_mode[chat_id] = "normal"
                self._settings_state.pop(chat_id, None)
                await self.bot.answer_callback_query(
                    callback.id, text=ui_t("port.callback.close_answer")
                )
                await self.bot.send_message(int(chat_id), ui_t("port.callback.close_message"))
                return

        # === 阶段 3 新增：处理偏好消化审批 ===
        if data and data.startswith("digest:"):
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

                    await self.bot.edit_message_text(
                        chat_id=callback.message.chat.id,
                        message_id=callback.message.message_id,
                        text=ui_t("port.digest.approved_message"),
                    )

                elif action == "reject_all":
                    with open(cand_path, "w", encoding="utf-8") as f:
                        f.write(digest_stub)
                    await self.bot.edit_message_text(
                        chat_id=callback.message.chat.id,
                        message_id=callback.message.message_id,
                        text=ui_t("port.digest.rejected_message"),
                    )
            except Exception as e:
                logger.error(boot_t("boot.log.telegram_digest_cb_fail", detail=str(e)))

            return
        # =================================================

        # === Restart confirmation ===
        if data and data.startswith("restart:"):
            chat_id = (
                str(callback.message.chat.id) if callback.message else str(callback.from_user.id)
            )
            act = data.split(":", 1)[1]
            if act == "confirm":
                ok = confirm_process_restart(chat_id, platform="telegram")
                await self.bot.answer_callback_query(
                    callback.id, text=ui_t("port.menu.restart_toast")
                )
                if ok:
                    await self.bot.send_message(int(chat_id), ui_t("port.menu.restart_ack"))
                else:
                    await self.bot.send_message(int(chat_id), ui_t("port.menu.restart_unavailable"))
                return
            if act == "cancel":
                cancel_process_restart(chat_id)
                await self.bot.answer_callback_query(
                    callback.id, text=ui_t("port.callback.close_answer")
                )
                await self.bot.send_message(int(chat_id), ui_t("port.callback.close_message"))
                return

        # === Task queue resume/discard ===
        if data and data.startswith("queue:"):
            chat_id = (
                str(callback.message.chat.id) if callback.message else str(callback.from_user.id)
            )
            act = data.split(":", 1)[1]
            if act == "discard":
                discard_task_queue(chat_id, platform="telegram")
                await self.bot.answer_callback_query(
                    callback.id, text=ui_t("shell.queue.discarded")
                )
                await self.bot.send_message(int(chat_id), ui_t("shell.queue.discarded"))
                return
            if act == "resume":
                await self.bot.answer_callback_query(callback.id, text=ui_t("shell.queue.resuming"))
                resume_task_queue(chat_id, platform="telegram")
                return

        # === Report Studio wizard (module: report_studio) ===
        if data and data.startswith("report:"):
            chat_id = (
                str(callback.message.chat.id) if callback.message else str(callback.from_user.id)
            )
            action = data.split(":", 1)[1]

            if action.startswith("now:"):
                sub = action.split(":", 1)[1]
                if sub not in ("daily", "weekly", "monthly"):
                    await self.bot.answer_callback_query(
                        callback.id, text=ui_t("dp.report.err_bad_type")
                    )
                    return
                await self.bot.answer_callback_query(
                    callback.id, text=ui_t("port.report.immediate_run_toast", rtype=sub)
                )
                await self.bot.send_message(
                    int(chat_id), ui_t("port.report.immediate_queued", rtype=sub)
                )
                msg = callback.message
                evt = self.create_event(
                    task=f"/report run {sub}",
                    platform="telegram",
                    priority=EventPriority.HIGH,
                    chat_id=chat_id,
                    raw_content=data,
                    **(self._locale_kw_from_message(msg) if msg else {}),
                )
                await self.publish(evt)
                return

            st = self._report_wizard.get(chat_id) or {
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
                await self.send_interactive_buttons(int(chat_id), text, buttons)

            if action in ("open", "start"):
                st["stage"] = "choose_type"
                self._report_wizard[chat_id] = st
                await self.bot.answer_callback_query(
                    callback.id, text=ui_t("port.report.wizard_toast")
                )
                await _send(report_wizard_intro(), report_type_buttons())
                return

            if action == "cancel":
                self._report_wizard.pop(chat_id, None)
                await self.bot.answer_callback_query(
                    callback.id, text=ui_t("port.report.cancel_toast")
                )
                await self.bot.send_message(int(chat_id), ui_t("port.report.cancel_message"))
                return

            if action.startswith("type:"):
                rt = action.split(":", 1)[1]
                st["report_type"] = rt
                st["stage"] = "choose_sections"
                self._report_wizard[chat_id] = st
                await self.bot.answer_callback_query(
                    callback.id, text=ui_t("port.report.type_selected_toast", rtype=rt)
                )
                sec = st["sections"]
                await _send(report_sections_intro(rt), report_section_toggle_buttons(sec))
                return

            if action.startswith("toggle:"):
                key = action.split(":", 1)[1]
                if key in st["sections"]:
                    st["sections"][key] = not bool(st["sections"][key])
                self._report_wizard[chat_id] = st
                await self.bot.answer_callback_query(
                    callback.id, text=ui_t("port.report.toggle_updated_toast")
                )
                # re-render buttons
                rt = st.get("report_type") or "daily"
                sec = st["sections"]
                await _send(report_sections_intro(rt), report_section_toggle_buttons(sec))
                return

            if action == "next_schedule":
                st["stage"] = "await_schedule"
                self._report_wizard[chat_id] = st
                await self.bot.answer_callback_query(
                    callback.id, text=ui_t("port.report.schedule_prompt_toast")
                )
                await self.bot.send_message(
                    int(chat_id), ui_t("port.report.schedule_body_telegram")
                )
                return

            return

        # Step 8.1: ACTION-family intent templates — one-shot ack (no template execute until consumed).
        if data and data.startswith("intent_action_tpl:"):
            chat_id = (
                str(callback.message.chat.id) if callback.message else str(callback.from_user.id)
            )
            parts = data.split(":", 2)
            if len(parts) >= 3 and hitl_handler is not None:
                verb, cid = parts[1], parts[2]
                if verb == "approve":
                    hitl_handler.grant_intent_action_template_ack(cid)
                    toast = ui_t("intent.action_template.hitl_toast_confirmed")
                else:
                    toast = ui_t("intent.action_template.hitl_toast_aborted")
                await self.bot.answer_callback_query(callback.id, text=toast)
                await self.bot.send_message(int(chat_id), toast)
            else:
                await self.bot.answer_callback_query(
                    callback.id, text=ui_t("port.hitl.operation_received_toast")
                )
            return

        # 原有 HITL resume 逻辑
        if data and data.startswith("resume:"):
            _, workflow_id, action = data.split(":")
            logger.info(
                boot_t(
                    "boot.log.telegram_hitl_resume",
                    workflow_id=workflow_id,
                    action=action,
                )
            )

            if hitl_handler is not None:
                await hitl_handler.process_resume(
                    workflow_id=workflow_id,
                    action=action,
                    user_input={"action": action} if action == "provide" else None,
                )

            await self.bot.answer_callback_query(
                callback.id, text=ui_t("port.hitl.operation_received_toast")
            )
            await self.bot.send_message(
                callback.from_user.id,
                ui_t(
                    "port.hitl.workflow_action_message",
                    workflow_id=workflow_id,
                    action=action,
                ),
            )
            return

    async def _handle_text(self, message: types.Message):
        chat_id = str(message.chat.id)
        text = (message.text or "").strip()
        if is_entry_menu_command(text):
            self._entry_mode[chat_id] = "normal"
            self._settings_state.pop(chat_id, None)
            self._report_wizard.pop(chat_id, None)
            await self._send_entry_menu(int(chat_id))
            return
        mode = self._entry_mode.get(chat_id, "normal")

        # Report wizard entrypoint (text trigger)
        if mode == "normal":
            norm = text.lower().strip()
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
                self._report_wizard[chat_id] = st
                await self.send_interactive_buttons(
                    int(chat_id),
                    report_wizard_intro(),
                    report_type_buttons(),
                )
                return

        # Report wizard schedule input (only in normal mode)
        if mode == "normal":
            st = self._report_wizard.get(chat_id)
            if st and st.get("stage") == "await_schedule":
                parts = text.split()
                if len(parts) >= 2:
                    tz = parts[0].strip()
                    hhmm = parts[1].strip()
                    rt = st.get("report_type") or "daily"
                    updates = {
                        "schedule": {"timezone": tz, "publish_time_hhmm": hhmm},
                        "sections": dict(st.get("sections") or {}),
                    }
                    # publish a /report set event so DecisionProcessor handles validation+persist
                    evt = self.create_event(
                        task=f'/report set {rt} {__import__("json").dumps(updates, ensure_ascii=False)}',
                        platform="telegram",
                        priority=EventPriority.HIGH,
                        chat_id=chat_id,
                        raw_content=text,
                        **self._locale_kw_from_message(message),
                    )
                    await self.publish(evt)
                    self._report_wizard.pop(chat_id, None)
                    await message.answer(
                        ui_t("port.report.schedule_submitted", rtype=rt, tz=tz, hhmm=hhmm)
                    )
                    return
                await message.answer(ui_t("port.report.schedule_bad_format"))
                return

        if mode == "settings":
            st = self._settings_state.get(chat_id) or ChatSettingsState(stage="category")
            st2, reply, _buttons = handle_text(st, text)
            self._settings_state[chat_id] = st2
            if getattr(st2, "start_report_wizard", False):
                self._entry_mode[chat_id] = "normal"
                self._settings_state.pop(chat_id, None)
                await message.answer(reply[:4000])
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
                self._report_wizard[chat_id] = stw
                await self.send_interactive_buttons(
                    int(chat_id),
                    report_wizard_intro(),
                    report_type_buttons(),
                )
                return
            if getattr(st2, "exit_to_main", False):
                self._entry_mode[chat_id] = "normal"
                self._settings_state.pop(chat_id, None)
                await message.answer(closed_settings_ack_text())
                await self._send_entry_menu(int(chat_id))
                return
            await message.answer(reply[:4000])
            return

        # 正常对话：发布事件（需要进入系统设置时请点击按钮）
        event = self.create_event(
            task=text,
            platform="telegram",
            priority=EventPriority.HIGH,
            chat_id=chat_id,
            raw_content=text,
            **self._locale_kw_from_message(message),
        )
        await self.publish(event)

    async def _send_entry_menu(self, chat_id: int) -> None:
        """启动后入口菜单：正常对话 / 系统设置。"""
        self._entry_mode[str(chat_id)] = "normal"
        await self.send_interactive_buttons(chat_id, menu_text(), entry_menu_telegram_buttons())

    async def _handle_voice(self, message: types.Message):
        tmp_path = None
        try:
            file_info = await self.bot.get_file(message.voice.file_id)
            downloaded_file = await self.bot.download_file(file_info.file_path)

            with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
                tmp_path = tmp.name

            async with aiofiles.open(tmp_path, "wb") as f:
                await f.write(downloaded_file.read())

            timeout = aiohttp.ClientTimeout(total=30)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                with open(tmp_path, "rb") as audio_file:
                    form = aiohttp.FormData()
                    form.add_field(
                        "file", audio_file, filename="voice.ogg", content_type="audio/ogg"
                    )
                    form.add_field("model", "whisper-1")
                    headers = {"Authorization": f"Bearer {self.openai_api_key}"}
                    async with session.post(
                        "https://api.openai.com/v1/audio/transcriptions", data=form, headers=headers
                    ) as resp:
                        data = await resp.json()
                        transcribed_text = data.get("text", ui_t("port.telegram.voice_fallback"))

            task_instruction = ui_t(
                "port.telegram.voice_task",
                text=transcribed_text,
            )
            event = self.create_event(
                task=task_instruction,
                platform="telegram",
                priority=EventPriority.HIGH,
                chat_id=str(message.chat.id),
                media_type="voice",
                original_text=transcribed_text,
                **self._locale_kw_from_message(message),
            )
            await self.publish(event)
            preview = transcribed_text[:100] + ("..." if len(transcribed_text) > 100 else "")
            await message.answer(ui_t("port.telegram.voice_preview", preview=preview))

        except Exception as e:
            logger.error(boot_t("boot.log.telegram_voice_fail", detail=str(e)), exc_info=True)
            await message.answer(ui_t("port.telegram.voice_fail_user"))
        finally:
            if tmp_path and os.path.exists(tmp_path):
                self._schedule_cleanup(tmp_path, delay=180)

    async def _handle_visual(self, message: types.Message):
        try:
            if message.photo:
                media = message.photo[-1]
            elif message.video:
                media = message.video
            else:
                media = message.video_note

            file_info = await self.bot.get_file(media.file_id)
            downloaded_file = await self.bot.download_file(file_info.file_path)

            with BytesIO(downloaded_file.read()) as img_data:
                base64_img = base64.b64encode(img_data.getvalue()).decode("utf-8")

            event = self.create_event(
                task=ui_t("port.telegram.visual_task"),
                platform="telegram",
                priority=EventPriority.HIGH,
                chat_id=str(message.chat.id),
                media_type="photo",
                image_base64=base64_img,
                caption=message.caption or ui_t("port.telegram.visual_caption_default"),
                **self._locale_kw_from_message(message),
            )
            await self.publish(event)
            await message.answer(ui_t("port.telegram.visual_received"))

        except Exception as e:
            logger.error(boot_t("boot.log.telegram_visual_fail", detail=str(e)), exc_info=True)
            await message.answer(ui_t("port.telegram.visual_fail_user"))

    async def _handle_document(self, message: types.Message):
        tmp_path = None
        try:
            file_info = await self.bot.get_file(message.document.file_id)
            downloaded_file = await self.bot.download_file(file_info.file_path)

            with tempfile.NamedTemporaryFile(
                delete=False, suffix=os.path.splitext(message.document.file_name)[1]
            ) as tmp:
                tmp_path = tmp.name

            async with aiofiles.open(tmp_path, "wb") as f:
                await f.write(downloaded_file.read())

            event = self.create_event(
                task=ui_t("port.telegram.doc_task", name=message.document.file_name),
                platform="telegram",
                priority=EventPriority.HIGH,
                chat_id=str(message.chat.id),
                media_type="document",
                file_path=tmp_path,
                file_name=message.document.file_name,
                **self._locale_kw_from_message(message),
            )
            await self.publish(event)
            await message.answer(
                ui_t("port.telegram.doc_received", name=message.document.file_name)
            )

            self._schedule_cleanup(tmp_path, delay=180)

        except Exception as e:
            logger.error(boot_t("boot.log.telegram_doc_fail", detail=str(e)), exc_info=True)
            await message.answer(ui_t("port.telegram.doc_fail_user"))
            if tmp_path and os.path.exists(tmp_path):
                os.unlink(tmp_path)

    async def update_ui_thought(self, chat_id: int, thought: Any):
        if not self.bot:
            return
        chat_id = chat_id or self.last_chat_id
        # 兼容外部传入 str chat_id（避免查不到 active_status，导致只停留在“多模态感知中...”）
        try:
            if isinstance(chat_id, str) and chat_id.isdigit():
                chat_id = int(chat_id)
        except Exception:
            pass
        if not chat_id:
            return
        if chat_id not in self.active_status:
            return

        msg_id = self.active_status[chat_id]
        display_text = str(thought).replace("*", "").replace("_", "").replace("`", "")[:297] + "..."
        ui_text = ui_t("port.telegram.thought_stream", preview=display_text)

        try:
            await self.bot.send_chat_action(chat_id=chat_id, action="typing")
        except:
            pass

        try:
            await self.bot.edit_message_text(chat_id=chat_id, message_id=msg_id, text=ui_text)
        except Exception as e:
            logger.warning(boot_t("boot.log.telegram_ui_edit_retry", detail=str(e)))
            record_notification_retry("telegram", "ui_thought_resend")
            try:
                new_msg = await self.bot.send_message(chat_id=chat_id, text=ui_text)
                self.active_status[chat_id] = new_msg.message_id
            except Exception as retry_e:
                logger.error(boot_t("boot.log.telegram_ui_resend_fail", detail=str(retry_e)))
                self.active_status.pop(chat_id, None)

    async def send_message(self, chat_id: int, text: str) -> bool:
        """【核心修复】强制清理思考消息 + 始终发送最终回复 + 详细日志"""
        if not self.bot:
            logger.error(boot_t("boot.log.telegram_send_not_initialized"))
            record_notification_send("telegram", "send_message", "skipped")
            return False
        if not chat_id or chat_id <= 0:
            chat_id = self.last_chat_id or self.default_chat_id
        if not chat_id or chat_id <= 0:
            logger.error(boot_t("boot.log.telegram_bad_chat_id"))
            record_notification_send("telegram", "send_message", "failure")
            return False

        # 仅记录警告，不阻挡任何实际回复
        if port_is_filler_reply_for_log(text):
            logger.warning(boot_t("boot.log.telegram_filler_reply", preview=text[:100]))

        # 【关键修复】强制清理思考消息（无论 delete 是否成功）
        if chat_id in self.active_status:
            try:
                await self.bot.delete_message(chat_id, self.active_status[chat_id])
                logger.debug(boot_t("boot.log.telegram_thought_deleted", chat_id=str(chat_id)))
            except Exception as e:
                logger.warning(boot_t("boot.log.telegram_thought_delete_warn", detail=str(e)))
            finally:
                self.active_status.pop(chat_id, None)  # 无论成功与否都清除状态

        try:
            await self.bot.send_message(chat_id=chat_id, text=text[:4000])
            logger.info(
                boot_t(
                    "boot.log.telegram_final_sent",
                    chat_id=str(chat_id),
                    length=str(len(text)),
                    preview=text[:120],
                )
            )
            record_notification_send("telegram", "send_message", "success")
            return True
        except Exception as e:
            logger.error(boot_t("boot.log.telegram_final_send_fail", detail=str(e)), exc_info=True)
            record_notification_send("telegram", "send_message", "failure")
            return False

    async def send_interactive_buttons(self, chat_id: int, text: str, buttons: List[Dict]):
        if not self.bot:
            logger.warning(boot_t("boot.log.telegram_buttons_no_bot"))
            record_notification_send("telegram", "send_interactive", "skipped")
            return

        keyboard = inline_keyboard_one_button_per_row(buttons)

        try:
            await self.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup={"inline_keyboard": keyboard},
            )
            logger.info(boot_t("boot.log.telegram_hitl_buttons", chat_id=chat_id))
            record_notification_send("telegram", "send_interactive", "success")
        except Exception as e:
            logger.error(
                boot_t("boot.log.telegram_buttons_send_fail", detail=str(e)),
                exc_info=True,
            )
            record_notification_send("telegram", "send_interactive", "failure")
            raise

    async def stop(self):
        logger.info(boot_t("boot.log.telegram_shutdown"))
        for task in list(self._background_tasks):
            if not task.done():
                task.cancel()
        if self.bot:
            try:
                await self.bot.session.close()
                logger.info(boot_t("boot.log.telegram_session_closed"))
            except Exception as e:
                logger.warning(boot_t("boot.log.telegram_session_close_warn", detail=str(e)))
        self._background_tasks.clear()
        await super().stop()

    async def get_status(self) -> dict:
        return {
            "running": getattr(self, "_running", False),
            "bot_ready": bool(self.bot),
            "last_chat_id": self.last_chat_id,
        }


# End of src/adami_kernel/nexus/telegram_sensory.py
