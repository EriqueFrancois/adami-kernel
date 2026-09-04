# src/adami_kernel/core/lifecycle_manager.py
# 文件路径: src/adami_kernel/core/lifecycle_manager.py
# 版本：v2.4（KernelContext 显式契约化 + system.events Semaphore 并发限流版）
# 修改时间：2026-04-08
# 修复目的：为 _event_consumer 添加 asyncio.Semaphore 并发上限，防止事件/任务风暴

import asyncio
import contextlib
import json
import logging
import sys as sys_module
import time
from pathlib import Path
from typing import Any, Dict, Optional

from rich.console import Console

from adami_kernel.config import settings
from adami_kernel.core.task_queue import TaskQueueStore
from adami_kernel.i18n import t
from adami_kernel.i18n.boot_msg import boot_t
from adami_kernel.nexus.event import AdamiEvent, EventPriority
from adami_kernel.nexus.shell import InteractiveShell


def _lm_t(key: str, **kwargs: Any) -> str:
    return t(key, locale=settings.effective_ui_default_locale(), **kwargs)


# ====================== 【本次核心修复】KernelContext 显式契约 ======================
from adami_kernel.observability.messenger_metrics import (
    record_notification_retry,
    record_notification_send,
)

# =================================================================================

logger = logging.getLogger("AdamI-LifecycleManager")
console = Console()


class LifecycleManager:
    """
    工业级生命周期管理器（单一职责）
    【v2.4 核心变更】：system.events 消费侧 Semaphore 限流（默认10，可配置），防止 create_task 风暴
    【v2.3 遗留功能】：KernelContext 显式契约化 + 必需字段最小区块
    【v2.2 遗留功能】：_format_cli_output NoneType.get 防护 + 完整代理属性与方法
    """

    def __init__(self, components: Dict[str, Any]):
        self.components = components
        self._running = True

        # ====================== 【KernelContext 必需区块】 ======================
        # 集中 DecisionProcessor 当前真实依赖的最小字段，满足 KernelContext Protocol
        self.active_sessions: Dict[str, dict] = {}
        self.session_locks: Dict[str, asyncio.Lock] = {}
        self.chat_locale_overrides: Dict[str, str] = {}
        self._hydrate_chat_locale_overrides()

        # CLI reply de-noising / de-duplication (best-effort).
        # Prevents repeated low-value replies and repeated busy banners from spamming the terminal.
        # Format: {chat_id: {"ts": float, "kind": str, "text": str}}
        self._cli_last_reply: Dict[str, Dict[str, Any]] = {}

        # ====================== Task queue (per chat, persistent) ======================
        self.task_queue = TaskQueueStore.from_settings(settings)
        endo = components.get("endocrine")
        if endo is not None and hasattr(endo, "set_task_queue"):
            endo.set_task_queue(self.task_queue)
        woof = components.get("woofish")
        if woof is not None and hasattr(woof, "set_task_queue"):
            woof.set_task_queue(self.task_queue)
        # ==============================================================================

        self.bus = components.get("bus")
        self.memory = components.get("memory")
        self.router = components.get("router")
        self.toolbox = components.get("toolbox")
        self.immunity = components.get("immunity")
        self.episodic_memory = components.get("episodic_memory")

        self.planner = components.get("planner")
        self.intent_router = components.get("intent_router")
        self.intent_template_registry = components.get("intent_template_registry")
        self.skill_router = components.get("skill_router")
        self.evolution_engine = components.get("evolution_engine")
        self.prompt_builder = components.get("prompt_builder")
        self.second_brain = components.get("second_brain")

        self.telegram_nerve = components.get("telegram_nerve")
        self.discord_nerve = components.get("discord_nerve")
        self.proprioception = components.get("proprioception")
        # =====================================================================

        # 【终极全面代理】保留原有全部字段（最小收敛原则）
        self.ans = components.get("ans")
        self.subconscious = components.get("subconscious")
        self.tls_vault = components.get("tls_vault")
        self.dream_sandbox = components.get("dream_sandbox")
        self.consolidator = components.get("consolidator")
        self.rl_loop = components.get("rl_loop")
        self.sub_agent_manager = components.get("sub_agent_manager")
        self.sensory = components.get("sensory")
        self.dlq = components.get("dlq")
        self.claw_hub = components.get("claw_hub")
        self.meta_cortex = components.get("meta_cortex")
        self.self_model = components.get("self_model")
        self.curiosity = components.get("curiosity")
        self.endocrine = components.get("endocrine")
        self.woofish = components.get("woofish")
        self.sensitive_filter = components.get("sensitive_filter")
        self.vector_store = components.get("vector_store")
        self.workflow_engine = components.get("workflow_engine")
        self.multi_agent_orchestrator = components.get("multi_agent_orchestrator")
        self.reflexion_loop = components.get("reflexion_loop")
        self.tdd_evolution = components.get("tdd_evolution")
        self.skill_composer = components.get("skill_composer")
        self.skill_manager = components.get("skill_manager")
        self.skill_version_manager = components.get("skill_version_manager")
        self.skill_cleaner = components.get("skill_cleaner")
        self.skill_optimizer = components.get("skill_optimizer")
        self.self_test_engine = components.get("self_test_engine")
        self.observability = components.get("observability")
        self.hitl_handler = components.get("hitl_handler")
        self.multi_tenant_guard = components.get("multi_tenant_guard")
        self.nerve_registry = components.get("nerve_registry")
        self.health_server = components.get("health_server")
        self.skill_market = components.get("skill_market")
        self.github_hunter = components.get("github_hunter")
        self.evolution_orchestrator = components.get("evolution_orchestrator")
        self.circadian_nerve = components.get("circadian_nerve")
        self.registry = components.get("registry")
        self.base_persona = components.get("base_persona", _lm_t("lc.persona.default"))

        # 【方法代理】一次性覆盖原始 kernel.py 中所有被外部调用的方法
        self._get_current_persona = lambda: self.base_persona
        self._send_reply = self._send_reply_proxy
        self._handle_system_action = self._handle_system_action_proxy
        self._parse_decision = self._parse_decision_proxy
        self._ensure_skill_metadata = self._ensure_skill_metadata_proxy

        self.background_tasks = []
        self.shell = None
        self._restart_process_after_shutdown = False
        self._lifecycle_finalize_lock: Optional[asyncio.Lock] = None
        self._lifecycle_shutdown_finished = False
        self._reexec_done = False

        from adami_kernel.core.restart_control import set_restart_target

        set_restart_target(self)

        # ====================== 【步骤3】system.events 并发上限（可配置 ADAMI_EVENT_CONSUMER_MAX_CONCURRENT） ======================
        _max_evt = max(1, int(settings.ADAMI_EVENT_CONSUMER_MAX_CONCURRENT))
        self._event_sem = asyncio.Semaphore(_max_evt)
        logger.info(boot_t("boot.log.lifecycle_event_consumer_cap", n=_max_evt))
        # =================================================================================

        logger.info(_lm_t("lcm.log.initializing"))

    def request_process_restart(self) -> None:
        """Shut down gracefully then replace this process (see ``run_forever`` finally)."""
        self._restart_process_after_shutdown = True
        self._running = False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(self._finalize_shutdown_and_maybe_reexec())

    # ====================== Restart with per-chat confirmation ======================
    def request_process_restart_for_chat(self, chat_id: str, platform: str) -> bool:
        """
        Telegram/Discord menu entrypoint.
        If there are unfinished tasks, ask for confirmation instead of restarting immediately.
        """
        cid = str(chat_id)
        pf = str(platform or "")
        tq = getattr(self, "task_queue", None)
        if tq is not None and tq.has_pending_or_in_progress(cid):
            if not hasattr(self, "_restart_confirm_pending"):
                self._restart_confirm_pending = {}  # type: ignore[attr-defined]
            self._restart_confirm_pending[cid] = True  # type: ignore[attr-defined]
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                return False
            loop.create_task(
                self._send_reply(
                    cid,
                    _lm_t("port.menu.restart_pending_prompt"),
                    platform=pf or "telegram",
                )
            )
            return False
        self.request_process_restart()
        return True

    def confirm_process_restart(self, chat_id: str, platform: str) -> bool:
        cid = str(chat_id)
        pending = getattr(self, "_restart_confirm_pending", {}) or {}
        if not pending.get(cid):
            # nothing pending; treat as normal restart request
            self.request_process_restart()
            return True
        pending[cid] = False
        self._restart_confirm_pending = pending  # type: ignore[attr-defined]
        self.request_process_restart()
        return True

    def cancel_process_restart(self, chat_id: str) -> bool:
        cid = str(chat_id)
        pending = getattr(self, "_restart_confirm_pending", {}) or {}
        if pending.get(cid):
            pending[cid] = False
            self._restart_confirm_pending = pending  # type: ignore[attr-defined]
        return True

    # ==============================================================================

    # ====================== Queue resume/discard (per chat, per platform) ======================
    def resume_task_queue_for_chat(self, chat_id: str, platform: str) -> bool:
        tq = getattr(self, "task_queue", None)
        if tq is None:
            return False
        cid = str(chat_id)
        try:
            nxt = tq.pop_next(cid)
        except Exception:
            nxt = None
        if nxt is None:
            return True
        src = {
            "cli": "user.prompt",
            "telegram": "sensory.telegram",
            "discord": "sensory.discord",
        }.get(str(platform).lower(), "user.prompt")
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        tid = str(getattr(nxt, "trace_id", "") or "").strip()
        ev = AdamiEvent(
            trace_id=tid if tid else f"cmd_q_{int(time.time() * 1000)}",
            source_module=src,
            target_topic="system.events",
            priority=EventPriority.HIGH,
            payload={"task": nxt.task, "chat_id": cid},
        )
        loop.create_task(self.bus.publish(ev))
        return True

    def discard_task_queue_for_chat(self, chat_id: str, platform: str) -> bool:
        tq = getattr(self, "task_queue", None)
        if tq is None:
            return False
        try:
            tq.discard_all(str(chat_id))
        except Exception:
            pass
        return True

    # ==============================================================================

    async def _finalize_shutdown_and_maybe_reexec(self) -> None:
        """Single-flight shutdown + optional execv (CLI / Telegram / Discord restart)."""
        if self._lifecycle_finalize_lock is None:
            self._lifecycle_finalize_lock = asyncio.Lock()
        async with self._lifecycle_finalize_lock:
            if not self._lifecycle_shutdown_finished:
                await self._shutdown()
                self._lifecycle_shutdown_finished = True
            if not self._restart_process_after_shutdown or self._reexec_done:
                return
            self._reexec_done = True
            import os

            console.print(_lm_t("lc.restart.reexec"))
            try:
                argv = [sys_module.executable] + (list(sys_module.argv) if sys_module.argv else [])
                os.execv(sys_module.executable, argv)
            except Exception as e:
                logger.error(_lm_t("lc.restart.exec_failed", e=e), exc_info=True)
                self._reexec_done = False

    def _chat_locale_overrides_path(self) -> Path:
        return Path(settings.path_chat_locale_overrides_json)

    def _hydrate_chat_locale_overrides(self) -> None:
        from adami_kernel.i18n.locale_resolve import load_chat_locale_map

        self.chat_locale_overrides = load_chat_locale_map(self._chat_locale_overrides_path())

    def persist_chat_locale_override(self, chat_id: str, locale: str) -> None:
        """Persist per-chat locale under ``ADAMI_DATA_DIR``/``chat_locale_overrides.json``."""
        from adami_kernel.i18n.locale_resolve import save_chat_locale_map
        from adami_kernel.i18n.locale_utils import normalize_locale

        cid = str(chat_id)
        loc = normalize_locale(locale)
        self.chat_locale_overrides[cid] = loc
        save_chat_locale_map(self._chat_locale_overrides_path(), self.chat_locale_overrides)

    # ====================== 【新增】CLI 输出格式化工具 ======================
    def _format_cli_output(self, text: str) -> str:
        """
        将可能包含 JSON 的文本格式化为简洁的 CLI 输出。
        优先尝试提取技能执行结果或创建成功消息。
        【v2.2 核心修复】：增加 NoneType.get 安全导航防护
        """
        if not text.strip():
            return text

        # 尝试解析 JSON
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # 如果整个文本不是 JSON，尝试查找 JSON 对象（可能被包裹）
            start = text.find("{")
            end = text.rfind("}")
            if start != -1 and end != -1:
                try:
                    data = json.loads(text[start : end + 1])
                except:
                    return text
            else:
                return text

        if not isinstance(data, dict):
            return text

        # ====================== 【核心修复】安全提取链路防 NoneType 穿透 ======================
        # 使用 or {} 确保当任何节点（如 Engineer/Executor）失败返回 None 时，赋予空字典兜底
        engineer_data = data.get("engineer") or {}
        skill_name = (
            engineer_data.get("skill_name")
            or data.get("skill_name")
            or _lm_t("lc.cli.unknown_skill")
        )

        executor_data = data.get("executor") or {}
        exec_result = executor_data.get("execution_result") or {}

        critic_data = data.get("critic") or {}
        critic_feedback = critic_data.get("feedback") or {}
        approved = (
            critic_feedback.get("approved", False) if isinstance(critic_feedback, dict) else False
        )
        # =================================================================================

        # 如果执行结果存在且成功
        if exec_result and exec_result.get("status") == "success":
            if "data" in exec_result:
                data_val = exec_result["data"]
                if isinstance(data_val, dict):
                    # 天气类结果
                    if "city" in data_val and "temperature" in data_val:
                        msg = (data_val.get("message") or "").strip()
                        if not msg:
                            msg = _lm_t(
                                "lc.skill_created.weather_detail",
                                city=str(data_val.get("city") or ""),
                                condition=str(data_val.get("condition") or ""),
                                temperature=str(data_val.get("temperature") or ""),
                            )
                        return _lm_t(
                            "lc.skill_created.pass_with_tests",
                            skill_name=skill_name,
                            test_result=msg,
                        )
                    if "price" in data_val or isinstance(data_val, str):
                        return _lm_t(
                            "lc.skill_created.pass_data_only",
                            skill_name=skill_name,
                            test_result=str(data_val),
                        )
                elif isinstance(data_val, str):
                    return _lm_t(
                        "lc.skill_created.pass_data_only",
                        skill_name=skill_name,
                        test_result=data_val,
                    )
            if exec_result.get("message"):
                return _lm_t(
                    "lc.skill_created.pass_message",
                    skill_name=skill_name,
                    test_result=str(exec_result["message"]),
                )
            return _lm_t("lc.skill_created.pass_short", skill_name=skill_name)

        if approved:
            return _lm_t("lc.skill_created.approved_only", skill_name=skill_name)

        if "error" in data:
            return _lm_t("lc.skill_created.failed", detail=str(data["error"]))

        # 无法识别，返回原始文本
        return text

    # =================================================================================

    # ====================== 【方法代理实现】 ======================
    async def _send_reply_proxy(
        self,
        chat_id: Optional[Any],
        text: str,
        platform: str = "telegram",
        *,
        trace_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        force_trace_footer: bool = False,
    ) -> None:
        """代理原始 _send_reply 方法（增强 CLI 用户反馈）"""
        if not chat_id:
            return

        # Optional: append a trace footer to the *final* result message (platform-aware).
        # We only do this when force_trace_footer is True to avoid polluting low-signal system banners.
        if force_trace_footer and isinstance(text, str):
            txt = str(text)
            low = txt.lower()
            has_trace = ("trace=`" in txt) or ("trace_id=" in low) or ("trace=" in low)
            has_wf = ("workflow_id=" in low) or ("workflow id=" in low)
            want_wf = bool(workflow_id and str(workflow_id).strip())
            want_trace = bool(trace_id and str(trace_id).strip())
            # Only append what's missing (avoid duplicating trace, but still allow adding workflow_id).
            parts = []
            if want_wf and not has_wf:
                parts.append(f"workflow_id={str(workflow_id).strip()}")
            if want_trace and not has_trace:
                parts.append(f"trace=`{str(trace_id).strip()}`")
            if parts:
                footer = " · ".join(parts)
                if str(platform).lower() == "cli":
                    txt = f"{txt}\n{footer}"
                else:
                    txt = f"{txt}\n\n{footer}"
                text = txt
                # Mark that this trace has a final-result footer (trace or workflow evidence).
                try:
                    if want_trace:
                        m = getattr(self, "_trace_footer_sent", None)
                        if m is None:
                            m = set()
                            self._trace_footer_sent = m
                        m.add((str(chat_id), str(trace_id)))
                except Exception:
                    pass

        # 【核心增强】CLI 平台直接控制台输出，并自动格式化 JSON
        if platform == "cli" or str(chat_id).lower() in ("cli", "default"):
            # Best-effort CLI spam suppression.
            # - suppress repeated busy banners within a short window
            # - suppress repeated "filler" replies within a short window
            try:
                cid = str(chat_id)
                now = time.time()
                prev = self._cli_last_reply.get(cid) or {}
                last_busy_ts = float(prev.get("last_busy_ts") or 0.0)
                last_filler_ts = float(prev.get("last_filler_ts") or 0.0)

                is_busy = isinstance(text, str) and "正在处理你的上一个请求" in text  # adami:allow-cjk busy-throttle legacy zh substring
                if is_busy and (now - last_busy_ts) < 3.0:
                    return

                from adami_kernel.i18n.ui_static import port_is_filler_reply_for_log

                is_filler = isinstance(text, str) and port_is_filler_reply_for_log(text)
                if is_filler and (now - last_filler_ts) < 15.0:
                    return

                if is_busy:
                    prev["last_busy_ts"] = now
                if is_filler:
                    prev["last_filler_ts"] = now
                prev["ts"] = now
                prev["kind"] = "busy" if is_busy else ("filler" if is_filler else "normal")
                prev["text"] = text[:120]
                self._cli_last_reply[cid] = prev
            except Exception:
                pass
            formatted = self._format_cli_output(text)
            console.print(f"{_lm_t('lc.console.cli_reply')}{formatted}")
            return

        # telegram 要求整数 chat_id
        if platform == "telegram" and self.telegram_nerve:
            try:
                if isinstance(chat_id, str) and chat_id.isdigit():
                    chat_id = int(chat_id)
                elif not isinstance(chat_id, int):
                    logger.warning(_lm_t("lcm.warn.tg_chat_id", typ=type(chat_id).__name__))
                    console.print(f"{_lm_t('lc.console.fallback_telegram')}{text}")
                    record_notification_send("telegram", "reply_proxy", "failure")
                    return
                await self.telegram_nerve.send_message(chat_id, text)
            except Exception as e:
                logger.warning(_lm_t("lcm.warn.tg_send", e=e))
                record_notification_send("telegram", "reply_proxy", "failure")
                console.print(f"{_lm_t('lc.console.fallback_telegram')}{text}")

        # discord 使用字符串 chat_id
        elif platform == "discord" and self.discord_nerve:
            try:
                await self.discord_nerve.send_message(str(chat_id), text)
            except Exception as e:
                logger.warning(_lm_t("lcm.warn.dc_send", e=e))
                record_notification_send("discord", "reply_proxy", "failure")
                console.print(f"{_lm_t('lc.console.fallback_discord')}{text}")

        else:
            logger.debug(_lm_t("lcm.debug.send_reply", cid=chat_id, pf=platform))
            console.print(f"{_lm_t('lc.console.default_reply')}{text}")

    async def _handle_system_action_proxy(
        self, cmd: str, current_chat_id: Optional[str], platform: str = "telegram"
    ) -> None:
        """代理原始 _handle_system_action 方法"""
        reply = _lm_t("lc.system_action.ok")
        logger.info(_lm_t("lcm.log.system_cmd", cmd=cmd))
        await self._send_reply_proxy(current_chat_id, reply, platform)

    def _parse_decision_proxy(self, response: str) -> tuple[str, dict]:
        """代理原始 _parse_decision 方法"""
        from adami_kernel.cortex.tools.json_parser import extract_json_from_llm_output

        action = "THINK"
        args: dict = {}
        data = extract_json_from_llm_output(response)
        if data:
            action = data.get("action", "THINK").upper()
            args = data.get("args", {})
        return action, args

    async def _ensure_skill_metadata_proxy(self):
        """代理原始 _ensure_skill_metadata 方法"""
        if self.skill_manager and hasattr(self.skill_manager, "_ensure_skill_metadata"):
            await self.skill_manager._ensure_skill_metadata()
        else:
            logger.debug(_lm_t("lcm.debug.ensure_meta_skip"))

    # =================================================================================

    async def run_forever(self) -> None:
        """完整运行时生命周期"""
        logger.info(boot_t("boot.log.lifecycle_main_loop"))

        self.background_tasks = [
            asyncio.create_task(self._event_consumer()),
            asyncio.create_task(self.components["ans"].start()),
            asyncio.create_task(self.components["health_server"].start()),
        ]

        if self.components.get("policy_loader"):
            self.background_tasks.append(
                asyncio.create_task(self.components["policy_loader"].poll_reload())
            )
            logger.info(boot_t("boot.log.lifecycle_policy_reload"))

        if settings.ADAMI_TRAIN_SCHEDULE_ENABLED:
            from adami_kernel.training.schedule import scheduled_training_loop

            self.background_tasks.append(asyncio.create_task(scheduled_training_loop()))
            logger.info(
                boot_t(
                    "boot.log.lifecycle_train_scheduled",
                    tz=settings.ADAMI_TRAIN_SCHEDULE_TZ,
                    hour=int(settings.ADAMI_TRAIN_SCHEDULE_HOUR),
                    minute=int(settings.ADAMI_TRAIN_SCHEDULE_MINUTE),
                    experience=settings.resolved_experience_dir,
                )
            )

        if getattr(settings, "ADAMI_IDLE_TRAIN_ENABLED", True):
            from adami_kernel.training.idle_schedule import idle_training_loop

            self.background_tasks.append(asyncio.create_task(idle_training_loop()))

        if self.components.get("web_console_task"):
            self.background_tasks.append(self.components["web_console_task"])

        if self.components.get("proprioception"):
            self.background_tasks.append(
                asyncio.create_task(self.components["proprioception"].start_monitoring())
            )
            self.components["ans"].set_proprioception(self.components["proprioception"])

        # MCP 后台加载与热更新（不阻塞内核启动）
        if self.components.get("mcp_manager") is not None:
            try:
                self.background_tasks.append(
                    asyncio.create_task(self.components["mcp_manager"].run_background())
                )
                logger.info(boot_t("boot.log.lifecycle_mcp_bg"))
            except Exception as e:
                logger.warning(boot_t("boot.log.lifecycle_mcp_bg_fail", detail=str(e)))

        await self.components["nerve_registry"].start_all(self.background_tasks)

        # After nerves are up: TTL sweep + optional pending-queue notify (off by default).
        self.background_tasks.append(
            asyncio.create_task(self._notify_pending_task_queues_on_boot())
        )
        sweep_sec = float(getattr(settings, "ADAMI_TASK_QUEUE_SWEEP_SEC", 0.0) or 0.0)
        if sweep_sec > 0:
            self.background_tasks.append(asyncio.create_task(self._sweep_task_queue_ttl_loop(sweep_sec)))
            logger.info(boot_t("boot.log.lifecycle_queue_sweep", sec=sweep_sec))

        self.shell = InteractiveShell(self)
        logger.info(boot_t("boot.log.lifecycle_shell_ok"))

        try:
            await self.shell.run()
        except KeyboardInterrupt:
            logger.info(boot_t("boot.log.lifecycle_shutdown_interrupt"))
        finally:
            await self._finalize_shutdown_and_maybe_reexec()

    async def _sweep_task_queue_ttl_loop(self, interval_sec: float) -> None:
        delay = max(5.0, float(interval_sec))
        while bool(getattr(self, "_running", True)):
            await asyncio.sleep(delay)
            tq = getattr(self, "task_queue", None)
            if tq is None:
                continue
            with contextlib.suppress(Exception):
                tq.persist_after_purge()

    async def _notify_pending_task_queues_on_boot(self) -> None:
        """
        On process start, if there are unfinished tasks in the persistent queue,
        optionally notify the user on chat platforms (Telegram/Discord).
        """
        # Allow nerves to finish bootstrapping. Discord in particular may need a few seconds
        # before ``bot.is_ready()`` becomes True.
        await asyncio.sleep(1.0)
        tq = getattr(self, "task_queue", None)
        if tq is None:
            return
        with contextlib.suppress(Exception):
            tq.persist_after_purge()
        if not bool(getattr(settings, "ADAMI_TASK_QUEUE_NOTIFY_ON_BOOT", False)):
            return
        for cid in tq.chat_ids_with_pending():
            recovered = False
            try:
                recovered = tq.recover_in_progress_to_front(cid) is not None
            except Exception:
                pass
            pending = []
            try:
                pending = tq.list_pending(cid)
            except Exception:
                pending = []
            if not pending:
                continue
            lines = [_lm_t("port.queue.pending_found", n=len(pending))]
            if recovered:
                lines.append(_lm_t("port.queue.recovered_in_progress"))
            for i, it in enumerate(pending[:8], start=1):
                preview = (it.task or "").strip().replace("\n", " ")
                if len(preview) > 80:
                    preview = preview[:79] + "…"
                lines.append(_lm_t("port.queue.pending_item", i=i, text=preview))
            if len(pending) > 8:
                lines.append(_lm_t("port.queue.pending_more", n=len(pending) - 8))
            lines.append(_lm_t("port.queue.resume_or_discard"))
            msg = "\n".join(lines).strip()
            pf = str(tq.preferred_platform(cid) or "telegram")
            # Emit a replay-recordable marker event (no `task`, so it won't enter DP).
            if recovered and getattr(self, "bus", None) is not None:
                with contextlib.suppress(Exception):
                    await self.bus.publish(
                        AdamiEvent(
                            trace_id=f"queue_recover_{int(time.time() * 1000)}",
                            source_module="core.lifecycle",
                            target_topic="system.events",
                            priority=EventPriority.NORMAL,
                            payload={
                                "event_type": "QUEUE_RECOVERED",
                                "chat_id": str(cid),
                                "recovered": True,
                                "count_pending": int(len(pending)),
                            },
                        )
                    )
            try:
                if pf == "telegram" and getattr(self, "telegram_nerve", None) is not None:
                    for attempt in range(10):
                        try:
                            await self.telegram_nerve.send_interactive_buttons(
                                int(cid),
                                msg,
                                [
                                    {
                                        "text": _lm_t("port.queue.btn_resume"),
                                        "callback_data": "queue:resume",
                                    },
                                    {
                                        "text": _lm_t("port.queue.btn_discard"),
                                        "callback_data": "queue:discard",
                                    },
                                ],
                            )
                            break
                        except Exception:
                            if attempt < 9:
                                record_notification_retry("telegram", "boot_pending_queue")
                            await asyncio.sleep(0.6)
                    else:
                        # fall back to plain message
                        try:
                            await self._send_reply(cid, msg, platform=pf)
                        except Exception:
                            pass
                    continue
                if pf == "discord" and getattr(self, "discord_nerve", None) is not None:
                    sent = False
                    for attempt in range(12):
                        ok = await self.discord_nerve.send_interactive_buttons(
                            str(cid),
                            msg,
                            [
                                {
                                    "text": _lm_t("port.queue.btn_resume"),
                                    "callback_data": "queue:resume",
                                },
                                {
                                    "text": _lm_t("port.queue.btn_discard"),
                                    "callback_data": "queue:discard",
                                },
                            ],
                        )
                        if ok:
                            sent = True
                            break
                        if attempt < 11:
                            record_notification_retry("discord", "boot_pending_queue")
                        await asyncio.sleep(0.8)
                    if not sent:
                        try:
                            await self.discord_nerve.send_message(str(cid), msg)
                            sent = True
                        except Exception:
                            sent = False
                    if sent:
                        continue
                await self._send_reply(cid, msg, platform=pf)
            except Exception:
                continue

    async def _event_consumer(self) -> None:
        q = await self.components["bus"].subscribe("system.events")
        if not hasattr(self, "_chat_running_tasks"):
            self._chat_running_tasks = {}  # type: ignore[attr-defined]
        while self._running:
            try:
                ev = await asyncio.wait_for(
                    q.get(), float(settings.ADAMI_ORCHESTRATOR_QUEUE_POLL_SEC)
                )
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(_lm_t("lcm.err.event_consumer", e=e), exc_info=True)
                continue
            if bool(getattr(settings, "ADAMI_DP_EVENT_DEBUG", False)):
                try:
                    logger.info(
                        "[event_consumer] recv trace_id=%s src=%s chat_id=%s task=%r",
                        str(getattr(ev, "trace_id", "") or ""),
                        str(getattr(ev, "source_module", "") or ""),
                        str((getattr(ev, "payload", {}) or {}).get("chat_id", "default")),
                        str((getattr(ev, "payload", {}) or {}).get("task", "")),
                    )
                except Exception:
                    pass
            # Only user/task-bearing events should enter the DecisionProcessor.
            # Internal telemetry (e.g. router/tool events) may share the same topic but does not
            # represent a user prompt and can cause duplicate routing / empty-task spam.
            try:
                payload = getattr(ev, "payload", None) or {}
                task_txt = str(payload.get("task", "") or "").strip() if isinstance(payload, dict) else ""
            except Exception:
                task_txt = ""
            if not task_txt:
                if bool(getattr(settings, "ADAMI_DP_EVENT_DEBUG", False)):
                    try:
                        logger.info(
                            "[event_consumer] skip_no_task trace_id=%s src=%s",
                            str(getattr(ev, "trace_id", "") or ""),
                            str(getattr(ev, "source_module", "") or ""),
                        )
                    except Exception:
                        pass
                continue

            async def run_one(event):
                from adami_kernel.cortex.decision_processor import DecisionProcessor

                cid = str(getattr(event, "payload", {}).get("chat_id", "default"))
                async with self._event_sem:
                    # Track the active DP task for cancellation support (`/queue cancel`).
                    # Note: this maps to the task running `DecisionProcessor.process` (not tool subtasks).
                    if not hasattr(self, "_chat_running_tasks"):
                        self._chat_running_tasks = {}  # type: ignore[attr-defined]
                    self._chat_running_tasks[cid] = asyncio.current_task()  # type: ignore[attr-defined]
                    try:
                        await DecisionProcessor(self).process(event)
                    finally:
                        try:
                            # Only clear if we still point to ourselves.
                            cur = asyncio.current_task()
                            if self._chat_running_tasks.get(cid) is cur:  # type: ignore[attr-defined]
                                self._chat_running_tasks.pop(cid, None)  # type: ignore[attr-defined]
                        except Exception:
                            pass

            t = asyncio.create_task(run_one(ev))

            def _consume_exc(_t: asyncio.Task) -> None:
                try:
                    _ = _t.exception()
                except asyncio.CancelledError:
                    return
                except Exception:
                    return

            t.add_done_callback(_consume_exc)

    def cancel_current_task_for_chat(self, chat_id: str, platform: str) -> bool:
        """Best-effort cancel the in-progress task for a chat.

        Safety model:
        - Cancels the asyncio Task running `DecisionProcessor.process` for this chat (if any).
        - `DecisionProcessor` is responsible for releasing locks in its `finally` block.
        - This is best-effort: some tool calls may ignore cancellation; hard-timeout still protects the queue.
        """
        _ = platform
        cid = str(chat_id)
        tasks = getattr(self, "_chat_running_tasks", {}) or {}
        t = tasks.get(cid)
        if t is None or getattr(t, "done", None) and t.done():
            return False
        try:
            t.cancel()
            return True
        except Exception:
            return False

    async def _shutdown(self) -> None:
        console.print(_lm_t("lc.shutdown.line"))
        self._running = False

        if self.components.get("evolution_orchestrator"):
            await self.components["evolution_orchestrator"].stop()

        if (
            self.components.get("web_console_task")
            and not self.components["web_console_task"].done()
        ):
            try:
                self.components["web_console_task"].cancel()
                await asyncio.wait_for(self.components["web_console_task"], timeout=2.0)
            except (asyncio.CancelledError, asyncio.TimeoutError):
                pass
            except Exception as e:
                logger.debug(_lm_t("lcm.debug.web_console_close", e=e))

        # 优先停止外部接入（Telegram/Discord 等），避免其阻塞 gather
        if self.components.get("nerve_registry"):
            with contextlib.suppress(Exception):
                await asyncio.wait_for(self.components["nerve_registry"].stop_all(), timeout=3.0)

        for t in self.background_tasks:
            if not t.done():
                t.cancel()

        # 防止后台任务不响应取消导致无法回到系统提示符
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await asyncio.wait_for(
                asyncio.gather(*self.background_tasks, return_exceptions=True),
                timeout=3.0,
            )

        if self.components.get("self_test_engine"):
            await self.components["self_test_engine"].shutdown()

        # stop_all 已提前做过（且有 timeout），这里不再阻塞重复等待
        if hasattr(self.components["health_server"], "stop"):
            with contextlib.suppress(Exception):
                await self.components["health_server"].stop()

        await self.components["bus"].shutdown() if hasattr(
            self.components["bus"], "shutdown"
        ) else None
        logger.info(boot_t("boot.log.lifecycle_shutdown_complete"))
        # 不要在 asyncio.run 管理的事件循环中 loop.stop()/sys.exit()：
        # 直接返回，让上层自然结束，保证能回到 mac 终端提示符。
        return


# --- END OF FILE src/adami_kernel/core/lifecycle_manager.py ---
# 文件路径：src/adami_kernel/core/lifecycle_manager.py
