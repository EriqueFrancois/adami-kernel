# --- START OF FILE shell.py ---

import asyncio
import logging  # ← 【本次核心修复】修复 NameError: name 'logging' is not defined
import os  # ← 用于检测 systemd 服务环境
import sys
import time

from rich.console import Console

from adami_kernel.config import settings
from adami_kernel.i18n import t
from adami_kernel.i18n.ui_static import is_entry_menu_command, ui_t
from adami_kernel.nexus.cli_settings_wizard import run_cli_settings_wizard
from adami_kernel.nexus.event import AdamiEvent, EventPriority

console = Console()
logger = logging.getLogger("AdamI-InteractiveShell")


def _nshell_t(key: str, **kwargs) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


def _menu_help_rich() -> str:
    return (
        f"\n[bold]1[/bold]  {ui_t('shell.menu.enter_prompt')}\n"
        f"[bold]2[/bold]  {ui_t('shell.menu.system_settings')}\n"
        f"[bold]3[/bold]  {ui_t('shell.menu.restart')}\n"
        f"[bold]4[/bold]  {ui_t('shell.menu.immediate_report')}\n"
        f"[bold]0[/bold]  {ui_t('shell.menu.exit')}\n"
    )


async def _read_line() -> str:
    line = await asyncio.to_thread(sys.stdin.readline)
    if not line:
        raise EOFError
    return line.strip()


class InteractiveShell:
    """CLI 交互外壳（已从 kernel.py 独立抽出）"""

    def __init__(self, kernel):
        self.kernel = kernel
        self.cnt = 1
        self._suppress_cli_hint_once = False

    async def run(self):
        """启动交互式命令行循环：一条就绪提示后进入提示符；/menu 打开入口菜单。"""
        is_background = bool(
            os.environ.get("INVOCATION_ID")
            or os.environ.get("SYSTEMD_EXEC_PID")
            or not sys.stdout.isatty()
        )
        if is_background:
            logger.info(_nshell_t("nshell.log.systemd_skip"))
            # 服务模式：不进入交互，但也不能立刻退出进程，否则会触发 LifecycleManager 立即 shutdown
            # 保持主循环存活，直到收到外部停止信号（kernel._running=False / SIGINT 等）。
            while self.kernel._running:
                await asyncio.sleep(1.0)
            return

        console.print(ui_t("port.boot.system_ready"))
        self._suppress_cli_hint_once = True

        # On restart, if there are unfinished tasks in the persistent queue, ask user.
        await self._maybe_recover_task_queue_on_start()

        while self.kernel._running:
            await self._prompt_loop()
            if not self.kernel._running:
                break

            console.print(_menu_help_rich())
            # 内层循环：空行不视为错误（启动后 stdin 上常见多余换行）；无效输入只重显 Choose，不整页重打菜单
            while True:
                console.print(f"[bold]{ui_t('shell.prompt.choose')}[/bold]", end="")
                sys.stdout.flush()
                try:
                    choice = await _read_line()
                except EOFError:
                    self.kernel._running = False
                    return

                if not choice:
                    continue

                if is_entry_menu_command(choice):
                    break

                if choice in {"0", "exit", "quit"}:
                    if await self._confirm_interrupt_if_pending("cli"):
                        console.print(f"\n[bold red]{ui_t('shell.exit.goodbye')}[/bold red]")
                        self.kernel._running = False
                        return
                    break
                if choice == "2":
                    try:
                        await run_cli_settings_wizard(console)
                    except KeyboardInterrupt:
                        console.print(f"\n[yellow]{ui_t('shell.settings.interrupted')}[/yellow]\n")
                    break
                if choice == "1":
                    await self._prompt_loop()
                    break
                if choice == "3":
                    if await self._confirm_interrupt_if_pending("cli"):
                        console.print(
                            f"\n[bold yellow]{ui_t('shell.restart.starting')}[/bold yellow]\n"
                        )
                        self.kernel.request_process_restart()
                        return
                    break
                if choice == "4":
                    await self._immediate_report_menu()
                    break

                console.print(f"[red]{ui_t('shell.choice.invalid')}[/red]\n")

    async def _prompt_loop(self) -> None:
        """进入提示符：读取 stdin 并发布 system.events。"""
        cli_chat_id = "cli"  # CLI 使用固定 chat_id，避免与 Telegram/Discord 冲突
        if cli_chat_id not in self.kernel.session_locks:
            self.kernel.session_locks[cli_chat_id] = asyncio.Lock()

        while self.kernel._running:
            try:
                if self._suppress_cli_hint_once:
                    self._suppress_cli_hint_once = False
                else:
                    console.print(f"[dim]{ui_t('shell.prompt.hint_main')}[/dim]")
                console.print(f"\n[bold green]{ui_t('shell.prompt.line')}[/bold green] ", end="")
                sys.stdout.flush()
                u_in = await _read_line()
                if not u_in:
                    continue
                if u_in.lower() in {"exit", "quit"}:
                    if await self._confirm_interrupt_if_pending(cli_chat_id):
                        console.print(f"\n[bold red]{ui_t('shell.exit.goodbye')}[/bold red]")
                        self.kernel._running = False
                        return
                    continue
                if is_entry_menu_command(u_in):
                    console.print(f"[dim]{ui_t('shell.prompt.back_to_menu')}[/dim]\n")
                    return
                if u_in == "back":
                    console.print(f"[dim]{ui_t('shell.prompt.back_to_menu')}[/dim]\n")
                    return

                # IMPORTANT: don't block user input on the session lock.
                # If a task is already running, publish immediately and let DecisionProcessor enqueue.
                lock = self.kernel.session_locks.get(cli_chat_id)
                trace_id = f"cmd_{self.cnt:03d}"
                cli_event = AdamiEvent(
                    trace_id=trace_id,
                    source_module="user.prompt",
                    target_topic="system.events",
                    priority=EventPriority.HIGH,
                    payload={"task": u_in, "chat_id": cli_chat_id},
                )
                if lock is not None and lock.locked():
                    await self.kernel.bus.publish(cli_event)
                    self.cnt += 1
                    continue

                async with self.kernel.session_locks[cli_chat_id]:
                    self.kernel.active_sessions[cli_chat_id] = {
                        "trace_id": trace_id,
                        "started_at": time.time(),
                    }
                    await self.kernel.bus.publish(cli_event)
                    self.cnt += 1
            except KeyboardInterrupt:
                console.print(f"\n[dim]{ui_t('shell.prompt.hint_interrupt')}[/dim]\n")
            except EOFError:
                self.kernel._running = False
                return
            except Exception as e:
                console.print(f"[bold red]{ui_t('shell.cli_error', error=e)}[/bold red]")

    async def _confirm_interrupt_if_pending(self, chat_id: str) -> bool:
        """If there are queued/in-progress tasks, ask whether to interrupt."""
        tq = getattr(self.kernel, "task_queue", None)
        if tq is None or not tq.has_pending_or_in_progress(str(chat_id)):
            return True
        console.print(ui_t("shell.queue.interrupt_prompt"))
        console.print(ui_t("shell.queue.interrupt_choose"), end="")
        sys.stdout.flush()
        try:
            ans = (await _read_line()).strip().lower()
        except EOFError:
            return False
        return ans in {"y", "yes", "确认", "是"}  # adami:allow-cjk - accept CN confirmations

    async def _immediate_report_menu(self) -> None:
        """CLI: pick daily / weekly / monthly → publish ``/report run`` (same as ports)."""
        cli_chat_id = "cli"
        if cli_chat_id not in self.kernel.session_locks:
            self.kernel.session_locks[cli_chat_id] = asyncio.Lock()

        console.print(f"\n[bold]{ui_t('shell.report.immediate_title')}[/bold]\n")
        console.print(ui_t("shell.report.immediate_body"))
        rmap = {"1": "daily", "2": "weekly", "3": "monthly"}
        while self.kernel._running:
            console.print(f"\n[bold]{ui_t('shell.report.immediate_choose')}[/bold]", end="")
            sys.stdout.flush()
            try:
                line = await _read_line()
            except EOFError:
                return
            if not line:
                continue
            if is_entry_menu_command(line):
                return
            if line == "0" or line.lower() == "back":
                return
            rtype = rmap.get(line)
            if not rtype:
                console.print(f"[red]{ui_t('shell.report.immediate_invalid')}[/red]")
                continue
            console.print(ui_t("shell.report.immediate_submitted", rtype=rtype))
            lock = self.kernel.session_locks.get(cli_chat_id)
            trace_id = f"cmd_{self.cnt:03d}"
            cli_event = AdamiEvent(
                trace_id=trace_id,
                source_module="user.prompt",
                target_topic="system.events",
                priority=EventPriority.HIGH,
                payload={"task": f"/report run {rtype}", "chat_id": cli_chat_id},
            )
            if lock is not None and lock.locked():
                await self.kernel.bus.publish(cli_event)
                self.cnt += 1
                return

            async with self.kernel.session_locks[cli_chat_id]:
                self.kernel.active_sessions[cli_chat_id] = {
                    "trace_id": trace_id,
                    "started_at": time.time(),
                }
                await self.kernel.bus.publish(cli_event)
                self.cnt += 1
            return

    async def _maybe_recover_task_queue_on_start(self) -> None:
        """If last run left tasks pending/in-progress, ask user to continue or discard."""
        tq = getattr(self.kernel, "task_queue", None)
        if tq is None:
            return
        cid = "cli"
        # Move in-progress back to queue head for user choice.
        try:
            tq.recover_in_progress_to_front(cid)
        except Exception:
            pass
        pending = []
        try:
            pending = tq.list_pending(cid)
        except Exception:
            pending = []
        if not pending:
            return
        console.print(ui_t("shell.queue.pending_found", n=len(pending)))
        for i, it in enumerate(pending[:8], start=1):
            preview = (it.task or "").strip().replace("\n", " ")
            if len(preview) > 80:
                preview = preview[:79] + "…"
            console.print(ui_t("shell.queue.pending_item", i=i, text=preview))
        if len(pending) > 8:
            console.print(ui_t("shell.queue.pending_more", n=len(pending) - 8))
        console.print(ui_t("shell.queue.resume_or_discard"))
        console.print(ui_t("shell.queue.resume_or_discard_choose"), end="")
        sys.stdout.flush()
        try:
            ans = (await _read_line()).strip().lower()
        except EOFError:
            return
        if ans in {"d", "discard", "drop", "丢弃", "n", "no"}:  # adami:allow-cjk - accept CN discard
            try:
                tq.discard_all(cid)
            except Exception:
                pass
            console.print(ui_t("shell.queue.discarded"))
            return
        # Default continue: dispatch first task immediately.
        try:
            nxt = tq.pop_next(cid)
        except Exception:
            nxt = None
        if nxt is None:
            return
        console.print(ui_t("shell.queue.resuming"))
        if cid not in self.kernel.session_locks:
            self.kernel.session_locks[cid] = asyncio.Lock()
        async with self.kernel.session_locks[cid]:
            self.kernel.active_sessions[cid] = {
                "trace_id": f"cmd_{self.cnt:03d}",
                "started_at": time.time(),
            }
            cli_event = AdamiEvent(
                trace_id=f"cmd_{self.cnt:03d}",
                source_module="user.prompt",
                target_topic="system.events",
                priority=EventPriority.HIGH,
                payload={"task": nxt.task, "chat_id": cid},
            )
            await self.kernel.bus.publish(cli_event)
            self.cnt += 1


# --- END OF FILE shell.py ---
