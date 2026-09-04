# src/adami_kernel/cortex/decision_processor.py
# 文件路径：src/adami_kernel/cortex/decision_processor.py
# 版本：v2.10（KernelContext 契约 + AGL 统一 agl_compat）
# 修改时间：2026-04-08
# 修复目的：将 DecisionProcessor 对 kernel 的隐式依赖显式化为 KernelContext 契约

import asyncio
import contextlib
import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple, Union

from pydantic import ValidationError
from rich.console import Console

from adami_kernel.config import settings

# ====================== 【本次修复】KernelContext 显式契约 ======================
from adami_kernel.core.kernel_context import KernelContext

# =====================================================================
from adami_kernel.cortex.decision_processor_report_actions import run_report_action
from adami_kernel.cortex.decision_processor_support import (
    SkillCreationPlan,
    TaskFailedException,
    _dcpu_t,
    _intake_archive_body_from_payload,
    _normalize_intake_suggested_para,
    _safe_intake_md_filename,
    _stop_audit_redact_and_trim,
    _yaml_single_quoted,
)

# =====================================================================
from adami_kernel.cortex.intent_adaptive.models import IntentFamily
from adami_kernel.cortex.intent_router import IntentSystemToken, extract_task_note_body
from adami_kernel.cortex.router import ResourceExhausted
from adami_kernel.cortex.tasks_md_utils import append_checkbox_under_todo_section

# ====================== 【本次修复】JSON 解析强化 ======================
from adami_kernel.cortex.tools.json_parser import extract_json_from_llm_output
from adami_kernel.hippocampus.second_brain import SecondBrainManager
from adami_kernel.i18n import t as i18n_t
from adami_kernel.i18n.locale_resolve import resolve_effective_locale
from adami_kernel.i18n.request_locale import (
    attach_request_locale,
    get_request_locale,
    reset_request_locale,
)
from adami_kernel.i18n.ui_static import task_matches_pipe_catalog
from adami_kernel.nexus.event import AdamiEvent, EventPriority
from adami_kernel.observability.activity_clock import touch_user_activity_from_event
from adami_kernel.observability.agl_compat import decision_tracer as tracer
from adami_kernel.orchestrator.planner import looks_like_planner_scratchpad
from adami_kernel.telemetry.experience_sink import (
    get_experience_sink,
    infer_tool_audit_meta,
    redact_payload,
    summarize_text,
)

console = Console()
logger = logging.getLogger("AdamI-DecisionProcessor")


# UTF-8 for 写作 — avoids bare CJK in this file for the Step-7 gate.
_WRITING_CMD_ZH = bytes.fromhex("e58699e4bd9c").decode("utf-8")


def _decision_reward(
    trace_id: str,
    reward: float,
    metadata: Optional[Dict[str, Any]] = None,
    *,
    source: str = "decision_processor",
) -> None:
    """经验池与 AGL 二选一，避免双写。"""
    meta = dict(metadata or {})
    if settings.ADAMI_EXPERIENCE_ENABLED:
        get_experience_sink().record_feedback(
            trace_id=str(trace_id),
            reward=float(reward),
            metadata=meta,
            source=source,
        )
    else:
        tracer.emit_reward(trace_id=trace_id, reward=float(reward), metadata=meta)


class DecisionProcessor:
    """决策处理器（God Object 最终解耦版）
    【v2.10 核心变更】：kernel 参数类型显式化为 KernelContext 契约；AGL 收口 agl_compat
    【v2.8 遗留功能】：Pydantic description 默认值 + NoneType.get 防护 + CLI 提示符强制恢复
    """

    def __init__(self, kernel: KernelContext):
        self.kernel = kernel
        self.episodic_memory = getattr(kernel, "episodic_memory", None)

        # ====================== 【延迟导入 SkillRouter，阻断 OTEL 错误链】 ======================
        self.skill_router = None
        if hasattr(kernel, "skill_router") and kernel.skill_router:
            self.skill_router = kernel.skill_router
        else:
            try:
                from adami_kernel.skill_manager.skill_router import SkillRouter

                self.skill_router = SkillRouter()
                logger.info(_dcpu_t("dcpu.log.skill_router_ok"))
            except Exception as e:
                logger.warning(_dcpu_t("dcpu.warn.skill_router_fail", e=e))
        # =================================================================================

    @staticmethod
    def _normalize_task_fingerprint(task_text: str) -> str:
        t = " ".join(str(task_text or "").strip().split()).lower()
        return t[:800] if t else ""

    async def _send_reply_once_per_trace(
        self,
        *,
        chat_id: str,
        trace_id: str,
        platform: str,
        text: str,
        kind: str = "fallback",
        dedupe_task: Optional[str] = None,
    ) -> bool:
        """Send a reply at most once per (chat_id, trace_id, kind).

        This is a safety net against duplicate event consumption or re-entrant fallback paths
        that would otherwise spam low-value replies for a single user prompt.
        """
        try:
            _lk = getattr(self.kernel, "_dp_reply_once_lock", None)
            if _lk is None:
                _lk = asyncio.Lock()
                self.kernel._dp_reply_once_lock = _lk
            async with _lk:
                seen: Set[Tuple[str, str, str]] = getattr(self.kernel, "_dp_reply_once", None)
                if seen is None:
                    seen = set()
                    self.kernel._dp_reply_once = seen
                key = (str(chat_id), str(trace_id), str(kind))
                if key in seen:
                    if bool(getattr(settings, "ADAMI_DP_EVENT_DEBUG", False)):
                        try:
                            logger.info(
                                "[dp.reply_once] skip duplicate key=%s",
                                str(key),
                            )
                        except Exception:
                            pass
                    return False
                seen.add(key)
                # Queue auto-dispatch historically minted fresh trace_ids per pop; duplicate the same
                # logical prompt needs idempotency tied to normalized task text as well.
                if str(kind) == "direct_answer":
                    fp = self._normalize_task_fingerprint(dedupe_task or "")
                    if fp:
                        fp_key = ("__direct_fp__", str(chat_id), fp)
                        if fp_key in seen:
                            if bool(getattr(settings, "ADAMI_DP_EVENT_DEBUG", False)):
                                try:
                                    logger.info(
                                        "[dp.reply_once] skip duplicate fp_key=%s",
                                        str(fp_key),
                                    )
                                except Exception:
                                    pass
                            return False
                        seen.add(fp_key)
        except Exception:
            # If tracking fails, still send the reply (best-effort).
            pass
        await self.kernel._send_reply(
            chat_id,
            text,
            platform=platform,
            trace_id=str(trace_id),
            force_trace_footer=(str(kind) == "direct_answer"),
        )
        return True

    async def _update_ui(self, chat_id: str, platform: str, thought: str):
        try:
            if platform == "telegram" and getattr(self.kernel, "telegram_nerve", None):
                await self.kernel.telegram_nerve.update_ui_thought(chat_id, thought)
            elif platform == "discord" and getattr(self.kernel, "discord_nerve", None):
                await self.kernel.discord_nerve.update_ui_thought(chat_id, thought)
        except Exception as e:
            logger.warning(_dcpu_t("dcpu.warn.ui_thought", e=e))

    def _throttle_should_send(self, chat_id: str, *, kind: str, window_sec: float) -> bool:
        """Best-effort cross-platform spam suppression for low-signal system replies."""
        try:
            now = time.time()
            m = getattr(self.kernel, "_dp_throttle", None)
            if m is None:
                m = {}
                self.kernel._dp_throttle = m
            key = (str(chat_id), str(kind))
            last = float(m.get(key) or 0.0)
            if last > 0 and (now - last) < float(window_sec):
                return False
            m[key] = now
            return True
        except Exception:
            return True

    def _safe_serialize(self, obj: Any) -> Any:
        if isinstance(obj, (dict, list, tuple)):
            return (
                {k: self._safe_serialize(v) for k, v in obj.items()}
                if isinstance(obj, dict)
                else [self._safe_serialize(item) for item in obj]
            )
        elif callable(obj):
            return f"<function {getattr(obj, '__name__', 'unknown')}>"
        else:
            try:
                import json

                json.dumps(obj)
                return obj
            except:
                return str(obj)

    def _format_cli_result(self, result: Union[Dict, Any]) -> str:
        if not isinstance(result, dict):
            return str(result)
        skill_name = (
            result.get("skill_name")
            or result.get("engineer", {}).get("skill_name")
            or i18n_t("dp.cli.skill_unknown")
        )
        if result.get("status") == "success":
            return i18n_t("dp.cli.skill_created_ok", skill_name=skill_name)
        return i18n_t("dp.cli.skill_created_fail", skill_name=skill_name)

    async def _dispatch_system_action(
        self,
        data: Any,
        task_text: str,
        chat_id: str,
        platform: str,
        payload: Optional[Dict[str, Any]] = None,
    ):
        if isinstance(data, tuple) and data[0] == "FORCE_OPTIMIZE":
            await self._handle_force_optimize_action(data[1], chat_id, platform)
        elif data == IntentSystemToken.MAINTAIN.value:
            await self._handle_maintain_action(chat_id, platform)
        elif data == IntentSystemToken.WRITING.value:
            await self._handle_writing_action(task_text, chat_id, platform)
        elif data == "DIGEST":
            await self._handle_digest_action(chat_id, platform)
        elif data == IntentSystemToken.REPORT.value:
            await self._handle_report_action(task_text, chat_id, platform)
        elif data in ["INTAKE", "INTAKE_AUTO"]:
            await self._handle_intake_action(task_text, chat_id, platform, payload or {})
        elif data == IntentSystemToken.TASK_NOTE.value:
            await self._handle_task_note_action(task_text, chat_id, platform)
        else:
            await self.kernel._handle_system_action(data, chat_id, platform)

    async def _handle_report_action(self, task_text: str, chat_id: str, platform: str) -> None:
        await run_report_action(self, task_text, chat_id, platform)

    async def _execute_action(
        self,
        action: str,
        args: Dict,
        chat_id: str,
        platform: str,
        trace_id: str,
        task_text: str = "",
    ):
        res: Any = None
        err_code: Optional[str] = None
        ok = True
        t0 = time.perf_counter()
        from adami_kernel.observability.tool_call_context import (
            reset_tool_trace_id,
            set_tool_trace_id,
        )

        token = set_tool_trace_id(str(trace_id))
        try:
            if action in ("ANALYZE_IMAGE", "PARSE_DOCUMENT"):
                if action == "ANALYZE_IMAGE":
                    image_b64 = args.get("image_base64") or ""
                    if image_b64 and hasattr(self.kernel.toolbox, "multi_modal"):
                        res = await self.kernel.toolbox.process_multimodal(
                            "photo",
                            {"image_base64": image_b64},
                            trace_id=str(trace_id),
                            timeout_sec=45.0,
                        )
                elif action == "PARSE_DOCUMENT":
                    file_path = args.get("file_path") or ""
                    if file_path and hasattr(self.kernel.toolbox, "multi_modal"):
                        res = await self.kernel.toolbox.process_multimodal(
                            "document",
                            {"file_path": file_path},
                            trace_id=str(trace_id),
                            timeout_sec=float(getattr(settings, "ADAMI_DOCUMENT_MARKDOWN_TIMEOUT_SEC", 45.0)),
                        )
            elif action in ("CREATE_NEW_SKILL", "UPDATE_SKILL"):
                skill_name = args.get("skill_name") or args.get("name") or "TEMP_SKILL"
                description = (
                    args.get("description")
                    or task_text[:100]
                    or i18n_t("dp.skill.user_created_description")
                )
                code = args.get("code") or args.get("python_code") or ""
                if not code or len(code.strip()) < 15:
                    res = i18n_t("dp.action.code_extract_failed")
                else:
                    res = await self.kernel.evolution_engine.create_new_skill(
                        skill_name=skill_name,
                        description=description,
                        code=code,
                        original_task_description=task_text,
                    )
            elif action == "EXECUTE_COMMAND":
                cmd = args.get("command", "")
                timeout_sec = args.get("timeout_sec", None)
                try:
                    timeout_sec_f = float(timeout_sec) if timeout_sec is not None else 30.0
                except (TypeError, ValueError):
                    timeout_sec_f = 30.0
                res = await self.kernel.immunity.run_with_timeout(
                    self.kernel.toolbox.execute_command(
                        str(cmd), timeout=timeout_sec_f, trace_id=str(trace_id)
                    ),
                    timeout=max(float(settings.ADAMI_SKILL_TIMEOUT), timeout_sec_f + 1.0),
                )

                # UX: timeout must be user-visible (and replayable).
                try:
                    exit_code = None
                    stderr = ""
                    if isinstance(res, dict):
                        exit_code = res.get("exit_code")
                        stderr = str(res.get("stderr") or "")
                    if exit_code == -1 and "timed out" in stderr.lower():
                        from adami_kernel.i18n.request_locale import get_request_locale

                        eff_loc2 = get_request_locale() or settings.effective_ui_default_locale()
                        msg = i18n_t(
                            "dp.tool.timeout_reply",
                            locale=eff_loc2,
                            timeout_sec=f"{timeout_sec_f:g}",
                            trace_id=str(trace_id),
                        )
                        await self.kernel._send_reply(chat_id, msg, platform=platform)
                        try:
                            await self.kernel.bus.publish(
                                AdamiEvent(
                                    trace_id=str(trace_id),
                                    source_module="nexus.reply",
                                    target_topic="system.events",
                                    priority=EventPriority.NORMAL,
                                    payload={"event_type": "REPLY", "text": str(msg), "trace_id": str(trace_id)},
                                )
                            )
                        except Exception:
                            pass
                except Exception:
                    pass
            elif action == "WEB_SEARCH":
                query = args.get("query", args.get("keywords", task_text))
                res = await self.kernel.toolbox.web_search(
                    str(query or ""),
                    max_results=int(args.get("max_results") or 5),
                    trace_id=str(trace_id),
                    timeout_sec=float(getattr(settings, "ADAMI_WEB_SEARCH_TIMEOUT_SEC", 30.0)),
                )
            elif action == "SEND_TELEGRAM":
                text = args.get("text", "")
                if self.kernel.telegram_nerve and chat_id:
                    res = await self.kernel.telegram_nerve.send_message(chat_id, text)
            elif action == "TASK_COMPLETE":
                console.print(i18n_t("dp.console.task_lifecycle_done"))
                return "TASK_COMPLETE"
            elif action == "THINK":
                res = i18n_t("dp.action.think_complete_use_tools")
            elif skill_func := self.kernel.evolution_engine.get_skill(action):
                coro = (
                    skill_func(**args)
                    if asyncio.iscoroutinefunction(skill_func)
                    else asyncio.to_thread(skill_func, **args)
                )
                res = await self.kernel.immunity.run_with_timeout(
                    coro, timeout=settings.ADAMI_SKILL_TIMEOUT
                )
            else:
                res = f"Unknown action: {action}. Use CREATE_NEW_SKILL to build it."
            return res
        except Exception as e:
            ok = False
            err_code = type(e).__name__
            raise
        finally:
            try:
                reset_tool_trace_id(token)
            except Exception:
                pass
            if action != "TASK_COMPLETE":
                latency_ms = (time.perf_counter() - t0) * 1000
                meta = infer_tool_audit_meta(self.kernel.evolution_engine, str(action))
                backend = str(meta.get("tool_backend") or "native")
                if action in (
                    "WEB_SEARCH",
                    "EXECUTE_COMMAND",
                    "ANALYZE_IMAGE",
                    "PARSE_DOCUMENT",
                    "SEND_TELEGRAM",
                    "THINK",
                ) or action in ("CREATE_NEW_SKILL", "UPDATE_SKILL"):
                    backend = "native"
                get_experience_sink().record_tool_call(
                    trace_id=str(trace_id),
                    tool_name=str(action),
                    tool_id=meta["tool_id"],
                    args_summary=summarize_text(str(redact_payload(args))),
                    result_summary=summarize_text(
                        str(redact_payload(res)) if res is not None else ""
                    ),
                    error_code=err_code,
                    ok=ok,
                    tool_backend=backend,
                    latency_ms=latency_ms,
                    docker_used=bool(meta.get("docker_used")),
                    mcp_allow_deny=str(meta.get("mcp_allow_deny") or "n/a"),
                    extra={
                        "platform": platform,
                        "chat_id": chat_id,
                        "path": "decision_processor._execute_action",
                    },
                )

    def _append_stop_audit_daily(
        self,
        task_text: str,
        chat_id: str,
        platform: str,
        trace_id: str,
    ) -> None:
        """stop_audit 最小版：本轮用户 task 一行摘要追加到 daily/YYYY-MM-DD.md（不含自动修复）。"""
        snippet = _stop_audit_redact_and_trim(task_text)
        if not snippet:
            return
        try:
            from datetime import datetime

            sb = getattr(self.kernel, "second_brain", None)
            root = (
                Path(sb.root).resolve()
                if sb is not None
                else Path(settings.path_second_brain_root).resolve()
            )
            day = datetime.now().strftime("%Y-%m-%d")
            daily_dir = root / "System" / "working-memory" / "daily"
            daily_dir.mkdir(parents=True, exist_ok=True)
            path = daily_dir / f"{day}.md"
            ts = datetime.now().strftime("%H:%M:%S")
            cid = chat_id if len(chat_id) <= 24 else chat_id[:21] + "…"
            tid = trace_id if len(trace_id) <= 20 else trace_id[:17] + "…"
            line = f"- `{ts}` {platform} `{cid}` trace=`{tid}` — {snippet}\n"
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
            logger.debug(_dcpu_t("dcpu.log.stop_audit", name=path.name))
        except Exception as e:
            logger.warning(_dcpu_t("dcpu.warn.stop_audit", e=e))

    def _write_session_export_log(
        self,
        task_text: str,
        chat_id: str,
        platform: str,
        trace_id: str,
    ) -> None:
        """\
        session_export 最小版：每轮完整 task 写入单文件（写死为按次落盘，非「当日一个大文件」追加）。

        路径：`System/session_logs/session_YYYYMMDD_HHMMSS.md`；同名冲突时加 `_1`、`_2`…
        正文前附带 YAML 头（时间戳与 trace 等元数据），其后为**未截断**的原始 task_text。
        """
        if not task_text or not str(task_text).strip():
            return
        try:
            from datetime import datetime

            sb = getattr(self.kernel, "second_brain", None)
            root = (
                Path(sb.root).resolve()
                if sb is not None
                else Path(settings.path_second_brain_root).resolve()
            )
            log_dir = root / "System" / "session_logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            now = datetime.now()
            stamp = now.strftime("%Y%m%d_%H%M%S")
            path = log_dir / f"session_{stamp}.md"
            n = 0
            while path.exists():
                n += 1
                path = log_dir / f"session_{stamp}_{n}.md"

            header = (
                "---\n"
                f"exported_at: {now.isoformat(timespec='seconds')}\n"
                f"platform: {platform}\n"
                f"chat_id: {chat_id}\n"
                f"trace_id: {trace_id}\n"
                "---\n\n"
            )
            with open(path, "w", encoding="utf-8") as f:
                f.write(header)
                f.write(task_text)
                if not task_text.endswith("\n"):
                    f.write("\n")
            logger.debug(_dcpu_t("dcpu.log.session_export", name=path.name))
        except Exception as e:
            logger.warning(_dcpu_t("dcpu.warn.session_export", e=e))

    async def process(self, event: AdamiEvent) -> None:
        touch_user_activity_from_event(event)
        chat_id = str(event.payload.get("chat_id", "default"))
        brain_root = None
        sb = getattr(self.kernel, "second_brain", None)
        if sb is not None:
            brain_root = getattr(sb, "root", None)
        effective_locale = resolve_effective_locale(
            payload=event.payload,
            chat_id=chat_id,
            chat_overrides=getattr(self.kernel, "chat_locale_overrides", {}) or {},
            brain_root=brain_root,
            brain_locale_rel=settings.ADAMI_BRAIN_LOCALE_JSON_RELATIVE,
            default_locale=settings.effective_ui_default_locale(),
            supported_locales=settings.ADAMI_SUPPORTED_LOCALES,
        )
        with tracer.start_as_current_span(
            "decision_processor.process",
            trace_id=event.trace_id,
            task_description=event.payload.get("task", "unknown task"),
            metadata={
                "chat_id": event.payload.get("chat_id"),
                "source": event.source_module,
                "locale": effective_locale,
            },
        ) as span:
            task_text = event.payload.get("task", "").strip()
            if bool(getattr(settings, "ADAMI_DP_EVENT_DEBUG", False)):
                try:
                    logger.info(
                        "[dp.process] enter trace_id=%s src=%s chat_id=%s task=%r",
                        str(getattr(event, "trace_id", "") or ""),
                        str(getattr(event, "source_module", "") or ""),
                        str(chat_id),
                        str(task_text),
                    )
                except Exception:
                    pass

            # ------------------------------------------------------------------
            # Do not re-enter the main intent-router for internal bus echoes.
            # - `cortex.feedback` is published by the slow-brain path; the bus fan-in
            #   would otherwise run `route_task` again on the same user text (duplicate
            #   Hybrid/LLM + duplicate user-visible replies). No other module subscribes
            #   to this stream for now.
            # - `nexus.reply` REPLY records (trace export) are not user prompts.
            # ------------------------------------------------------------------
            _srcm = str(getattr(event, "source_module", "") or "")
            if _srcm == "cortex.feedback":
                return
            if _srcm == "nexus.reply":
                return

            loc_token = attach_request_locale(effective_locale)
            try:
                platform = self._determine_platform(event.source_module)

                # Milestone A: queue health commands are handled locally and should not be queued
                # behind long-running tasks.
                task_low = (task_text or "").strip().lower()
                if task_low.startswith("/queue"):
                    tq_local = getattr(self.kernel, "task_queue", None)
                    bus_local = getattr(self.kernel, "bus", None)

                    async def _emit_reply_for_trace(text: str) -> None:
                        if not bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False)):
                            return
                        if bus_local is None:
                            return
                        try:
                            await bus_local.publish(
                                AdamiEvent(
                                    trace_id=str(event.trace_id),
                                    source_module="nexus.reply",
                                    target_topic="system.events",
                                    priority=EventPriority.NORMAL,
                                    payload={"event_type": "REPLY", "text": str(text)},
                                )
                            )
                        except Exception:
                            return

                    if task_low.startswith("/queue status"):
                        pending_n = 0
                        in_progress = False
                        pending_oldest_sec = 0
                        in_progress_sec = 0
                        try:
                            now = time.time()
                            pending = tq_local.list_pending(chat_id) if tq_local is not None else []
                            pending_n = len(pending)
                            if pending:
                                oldest = min(float(x.created_at) for x in pending if hasattr(x, "created_at"))
                                pending_oldest_sec = max(0, int(now - float(oldest)))
                            in_progress = (
                                tq_local.get_in_progress(chat_id) is not None
                                if tq_local is not None
                                else False
                            )
                            ip = tq_local.get_in_progress(chat_id) if tq_local is not None else None
                            if ip is not None and hasattr(ip, "started_at"):
                                in_progress_sec = max(0, int(now - float(ip.started_at)))
                        except Exception:
                            pending_n = 0
                            in_progress = False
                            pending_oldest_sec = 0
                            in_progress_sec = 0
                        msg = i18n_t(
                            "dp.queue.status_reply",
                            locale=effective_locale,
                            pending=int(pending_n),
                            in_progress=(1 if in_progress else 0),
                            pending_oldest_sec=int(pending_oldest_sec),
                            in_progress_sec=int(in_progress_sec),
                        )
                        await self.kernel._send_reply(chat_id, msg, platform=platform)
                        await _emit_reply_for_trace(msg)
                        return

                    if task_low.startswith("/queue discard"):
                        dropped = 0
                        had_ip = False
                        try:
                            if tq_local is not None:
                                dropped, had_ip = tq_local.discard_all(chat_id)
                        except Exception:
                            dropped, had_ip = 0, False
                        msg = i18n_t(
                            "dp.queue.discard_reply",
                            locale=effective_locale,
                            pending=int(dropped),
                            in_progress=(1 if had_ip else 0),
                        )
                        await self.kernel._send_reply(chat_id, msg, platform=platform)
                        await _emit_reply_for_trace(msg)
                        return

                    if task_low.startswith("/queue cancel"):
                        ok = False
                        try:
                            cancel_fn = getattr(self.kernel, "cancel_current_task_for_chat", None)
                            if callable(cancel_fn):
                                ok = bool(cancel_fn(chat_id, platform))
                        except Exception:
                            ok = False
                        msg = i18n_t(
                            "dp.queue.cancel_reply" if ok else "dp.queue.cancel_none",
                            locale=effective_locale,
                        )
                        await self.kernel._send_reply(chat_id, msg, platform=platform)
                        await _emit_reply_for_trace(msg)
                        return

                    if task_low.startswith("/queue export-trace"):
                        trace_id = ""
                        try:
                            trace_id = str(
                                (self.kernel.active_sessions.get(chat_id) or {}).get("trace_id") or ""
                            )
                        except Exception:
                            trace_id = ""
                        if trace_id:
                            msg = i18n_t(
                                "dp.queue.export_trace_reply",
                                locale=effective_locale,
                                trace_id=str(trace_id),
                            )
                        else:
                            msg = i18n_t(
                                "dp.queue.export_trace_none",
                                locale=effective_locale,
                            )
                        await self.kernel._send_reply(chat_id, msg, platform=platform)
                        await _emit_reply_for_trace(msg)
                        return
                # ------------------------------------------------------------------
                # Per-chat session turn: must be atomic vs. ``lock.locked()`` TOCTOU.
                # LifecycleManager may run up to ``ADAMI_EVENT_CONSUMER_MAX_CONCURRENT``
                # ``process()`` tasks; without a meta-lock, two tasks for the same
                # ``chat_id`` can both observe an unlocked session before either acquires,
                # causing duplicate intent-router / Hybrid work and duplicate replies.
                # ------------------------------------------------------------------
                if not await self._try_acquire_session_turn(chat_id, str(event.trace_id)):
                    if bool(getattr(settings, "ADAMI_DP_EVENT_DEBUG", False)):
                        try:
                            logger.info(
                                "[dp.process] session_busy trace_id=%s chat_id=%s",
                                str(getattr(event, "trace_id", "") or ""),
                                str(chat_id),
                            )
                        except Exception:
                            pass
                    tq = getattr(self.kernel, "task_queue", None)
                    queued_pos: int | None = None
                    queued_total: int | None = None
                    if tq is not None and task_text:
                        try:
                            pend = tq.list_pending(chat_id)
                            if any(
                                str(getattr(x, "task", "") or "").strip() == task_text.strip()
                                for x in pend
                            ):
                                msg_busy = i18n_t("dp.session.busy", locale=effective_locale)
                                if self._throttle_should_send(
                                    chat_id, kind="busy", window_sec=3.0
                                ):
                                    await self.kernel._send_reply(
                                        chat_id, msg_busy, platform=platform
                                    )
                                return
                            # Queue position includes the currently running task as position 1.
                            before = len(tq.list_pending(chat_id))
                            enq = tq.enqueue(
                                chat_id=chat_id,
                                task=task_text,
                                source_module=str(event.source_module),
                                platform=str(platform),
                                trace_id=str(event.trace_id),
                            )
                            if enq is None:
                                msg_cap = i18n_t(
                                    "dp.session.queue_capped", locale=effective_locale
                                )
                                if self._throttle_should_send(
                                    chat_id, kind="queue_capped", window_sec=5.0
                                ):
                                    await self.kernel._send_reply(
                                        chat_id, msg_cap, platform=platform
                                    )
                                return
                            queued_pos = before + 2
                            queued_total = before + 2
                        except Exception:
                            pass
                    if queued_pos is None:
                        msg_busy = i18n_t("dp.session.busy", locale=effective_locale)
                        if self._throttle_should_send(chat_id, kind="busy", window_sec=3.0):
                            await self.kernel._send_reply(
                                chat_id,
                                msg_busy,
                                platform=platform,
                            )
                        # Sim trace export: record user-visible reply in golden traces.
                        if bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False)):
                            bus_sim = getattr(self.kernel, "bus", None)
                            if bus_sim is not None:
                                try:
                                    await bus_sim.publish(
                                        AdamiEvent(
                                            trace_id=str(event.trace_id),
                                            source_module="nexus.reply",
                                            target_topic="system.events",
                                            priority=EventPriority.NORMAL,
                                            payload={"event_type": "REPLY", "text": msg_busy},
                                        )
                                    )
                                except Exception:
                                    pass
                        return
                    msg_q = i18n_t(
                        "dp.session.busy_queued",
                        locale=effective_locale,
                        trace_id=str(event.trace_id),
                        pos=int(queued_pos),
                        total=int(queued_total or queued_pos),
                    )
                    if self._throttle_should_send(
                        chat_id, kind="busy_queued", window_sec=2.0
                    ):
                        await self.kernel._send_reply(
                            chat_id,
                            msg_q,
                            platform=platform,
                        )
                    if bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False)):
                        bus_sim = getattr(self.kernel, "bus", None)
                        if bus_sim is not None:
                            try:
                                await bus_sim.publish(
                                    AdamiEvent(
                                        trace_id=str(event.trace_id),
                                        source_module="nexus.reply",
                                        target_topic="system.events",
                                        priority=EventPriority.NORMAL,
                                        payload={"event_type": "REPLY", "text": msg_q},
                                    )
                                )
                            except Exception:
                                pass
                    return

                if bool(getattr(settings, "ADAMI_DP_EVENT_DEBUG", False)):
                    try:
                        logger.info(
                            "[dp.process] session_acquired trace_id=%s chat_id=%s",
                            str(getattr(event, "trace_id", "") or ""),
                            str(chat_id),
                        )
                    except Exception:
                        pass
                await self._update_ui(chat_id, platform, i18n_t("dp.ui.thinking_stream"))
                # Mark this as in-progress for restart recovery.
                tq2 = getattr(self.kernel, "task_queue", None)
                if tq2 is not None and task_text:
                    try:
                        tq2.mark_started(
                            chat_id=chat_id,
                            trace_id=str(event.trace_id),
                            task=task_text,
                            source_module=str(event.source_module),
                            platform=str(platform),
                        )
                    except Exception:
                        pass

                # Lifecycle evidence: emit a single "started" message that includes trace_id,
                # so all ports (CLI/Telegram/Discord) have a user-visible correlation handle.
                try:
                    msg_started = i18n_t(
                        "dp.task.started",
                        locale=effective_locale,
                        trace_id=str(event.trace_id),
                    )
                    await self._send_reply_once_per_trace(
                        chat_id=chat_id,
                        trace_id=str(event.trace_id),
                        platform=platform,
                        text=msg_started,
                        kind="started",
                    )
                    if bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False)):
                        bus_sim = getattr(self.kernel, "bus", None)
                        if bus_sim is not None:
                            with contextlib.suppress(Exception):
                                await bus_sim.publish(
                                    AdamiEvent(
                                        trace_id=str(event.trace_id),
                                        source_module="nexus.reply",
                                        target_topic="system.events",
                                        priority=EventPriority.NORMAL,
                                        payload={"event_type": "REPLY", "text": msg_started},
                                    )
                                )
                except Exception:
                    pass

                # Track the running task for `/queue cancel` (works both under LifecycleManager consumer and
                # direct `dp.process(...)` calls used by golden trace capture).
                try:
                    if not hasattr(self.kernel, "_chat_running_tasks"):
                        self.kernel._chat_running_tasks = {}  # type: ignore[attr-defined]
                    cur = asyncio.current_task()
                    if cur is not None:
                        self.kernel._chat_running_tasks[str(chat_id)] = cur  # type: ignore[attr-defined]
                except Exception:
                    pass

                eid = str(event.trace_id)
                get_experience_sink().begin_episode(
                    eid,
                    eid,
                    push_context=True,
                    source="decision_processor.process",
                    platform=platform,
                )
                episode_outcome = "success"
                from adami_kernel.observability.timeout_budget import (
                    BudgetExceededError,
                    reset_task_timeout_budget,
                    set_task_timeout_budget,
                )
                budget_token = None
                self._skip_lifecycle_done = False

                try:

                    async def _run_one_task() -> None:
                        self._check_circuit_breaker(
                            event.payload.get("loop_depth", 0), event.trace_id
                        )

                        from adami_kernel.integration.sim.dp_offline_scenarios import (
                            try_handle_offline_sim,
                        )
                        if await try_handle_offline_sim(
                            self, event, task_text, chat_id, platform, effective_locale
                        ):
                            return

                        if self._handle_early_skill_creation(
                            task_text, chat_id, platform, event.trace_id
                        ):
                            _decision_reward(
                                str(event.trace_id),
                                1.0,
                                {"intent": "early_skill_creation"},
                            )
                            return

                        tag, data = await self.kernel.intent_router.route_task(task_text)
                        if tag == "SYSTEM_ACTION" and data in ("INTAKE", "INTAKE_AUTO"):
                            await self._dispatch_system_action(
                                data, task_text, chat_id, platform, event.payload
                            )
                            _decision_reward(str(event.trace_id), 1.0, {"intent": "intake"})
                            return

                        action_intent, args_intent = self._detect_multimodal_intent(event.payload)
                        if action_intent:
                            await self._dispatch_multimodal_task(
                                    action_intent,
                                    args_intent,
                                    chat_id,
                                    platform,
                                    event.trace_id,
                                    task_text,
                            )
                            _decision_reward(str(event.trace_id), 1.0, {"intent": "multimodal"})
                            return

                        if tag == "SYSTEM_ACTION":
                            await self._dispatch_system_action(
                                data, task_text, chat_id, platform, event.payload
                            )
                            if data == IntentSystemToken.REPORT.value:
                                self._skip_lifecycle_done = True
                        elif tag == "DIRECT_ANSWER":
                            await self._dispatch_direct_answer(
                                data, task_text, chat_id, platform, event.trace_id
                            )
                        elif tag == "COMPLEX_TASK":
                                # Lifecycle contract: "running" evidence (at least once) before long work.
                                try:
                                    msg_running = i18n_t(
                                        "dp.task.running",
                                        locale=effective_locale,
                                        trace_id=str(event.trace_id),
                                    )
                                    await self._send_reply_once_per_trace(
                                        chat_id=chat_id,
                                        trace_id=str(event.trace_id),
                                        platform=platform,
                                        text=msg_running,
                                        kind="running",
                                    )
                                    if bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False)):
                                        bus_sim = getattr(self.kernel, "bus", None)
                                        if bus_sim is not None:
                                            with contextlib.suppress(Exception):
                                                await bus_sim.publish(
                                                    AdamiEvent(
                                                        trace_id=str(event.trace_id),
                                                        source_module="nexus.reply",
                                                        target_topic="system.events",
                                                        priority=EventPriority.NORMAL,
                                                        payload={"event_type": "REPLY", "text": msg_running},
                                                    )
                                                )
                                except Exception:
                                    pass
                                await self._dispatch_complex_task(
                                    task_text,
                                    chat_id,
                                    platform,
                                    event.trace_id,
                                    router_data=data,
                                    trace_span=span,
                                )
                        else:
                            await self._dispatch_slow_brain(task_text, event, chat_id, platform)

                        _decision_reward(str(event.trace_id), 1.0, {"intent": tag})

                    hard_timeout = None
                    try:
                        if str(platform).lower() == "cli":
                            hard_timeout = float(
                                getattr(settings, "ADAMI_CLI_TASK_HARD_TIMEOUT_SEC", 0.0) or 0.0
                            )
                        else:
                            hard_timeout = float(
                                getattr(settings, "ADAMI_TASK_HARD_TIMEOUT_SEC", 0.0) or 0.0
                            )
                    except Exception:
                        hard_timeout = None
                    if hard_timeout is not None and hard_timeout > 0:
                        budget_token = set_task_timeout_budget(
                            str(event.trace_id), timeout_sec=float(hard_timeout)
                        )
                        await asyncio.wait_for(_run_one_task(), timeout=hard_timeout)
                    else:
                        await _run_one_task()
                    # Lifecycle contract: ensure a terminal "done" evidence message contains trace_id,
                    # even when the main result reply is produced elsewhere (DIRECT_ANSWER / planner / workflow).
                    try:
                        footer_sent = False
                        try:
                            sent = getattr(self.kernel, "_trace_footer_sent", None)
                            footer_sent = bool(
                                sent is not None and (str(chat_id), str(event.trace_id)) in sent
                            )
                        except Exception:
                            footer_sent = False
                        if footer_sent or bool(getattr(self, "_skip_lifecycle_done", False)):
                            # Report Studio already pushed the briefing; skip the extra "done" line.
                            pass
                        else:
                            msg_done = i18n_t(
                                "dp.task.done",
                                locale=effective_locale,
                                trace_id=str(event.trace_id),
                            )
                            await self._send_reply_once_per_trace(
                                chat_id=chat_id,
                                trace_id=str(event.trace_id),
                                platform=platform,
                                text=msg_done,
                                kind="done",
                            )
                            if bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False)):
                                bus_sim = getattr(self.kernel, "bus", None)
                                if bus_sim is not None:
                                    with contextlib.suppress(Exception):
                                        await bus_sim.publish(
                                            AdamiEvent(
                                                trace_id=str(event.trace_id),
                                                source_module="nexus.reply",
                                                target_topic="system.events",
                                                priority=EventPriority.NORMAL,
                                                payload={"event_type": "REPLY", "text": msg_done},
                                            )
                                        )
                    except Exception:
                        pass

                except ResourceExhausted as e:
                    episode_outcome = "rate_limited"
                    await self._handle_rate_limit(chat_id, platform, e)
                    _decision_reward(str(event.trace_id), 0.0, {"error": "rate_limit"})
                except BudgetExceededError:
                    episode_outcome = "timeout_budget_exceeded"
                    msg_budget = i18n_t(
                        "dp.task.timeout_budget_exceeded_released",
                        locale=effective_locale,
                        trace_id=str(event.trace_id),
                    )
                    await self._send_reply_once_per_trace(
                        chat_id=chat_id,
                        trace_id=str(event.trace_id),
                        platform=platform,
                        text=msg_budget,
                        kind="budget_exceeded",
                    )
                    if bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False)):
                        bus_sim = getattr(self.kernel, "bus", None)
                        if bus_sim is not None:
                            with contextlib.suppress(Exception):
                                await bus_sim.publish(
                                    AdamiEvent(
                                        trace_id=str(event.trace_id),
                                        source_module="nexus.reply",
                                        target_topic="system.events",
                                        priority=EventPriority.NORMAL,
                                        payload={"event_type": "REPLY", "text": msg_budget},
                                    )
                                )
                except asyncio.TimeoutError:
                    episode_outcome = "timeout"
                    msg_timeout = i18n_t(
                        "dp.task.hard_timeout_released",
                        locale=effective_locale,
                        trace_id=str(event.trace_id),
                        sec=int(hard_timeout or 0),
                    )
                    await self._send_reply_once_per_trace(
                        chat_id=chat_id,
                        trace_id=str(event.trace_id),
                        platform=platform,
                        text=msg_timeout,
                        kind="hard_timeout",
                    )
                    if bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False)):
                        bus_sim = getattr(self.kernel, "bus", None)
                        if bus_sim is not None:
                            try:
                                await bus_sim.publish(
                                    AdamiEvent(
                                        trace_id=str(event.trace_id),
                                        source_module="nexus.reply",
                                        target_topic="system.events",
                                        priority=EventPriority.NORMAL,
                                        payload={"event_type": "REPLY", "text": msg_timeout},
                                    )
                                )
                            except Exception:
                                pass
                    _decision_reward(str(event.trace_id), 0.0, {"error": "timeout"})
                except TaskFailedException:
                    episode_outcome = "task_failed"
                    msg_failed = i18n_t("dp.circuit.user", trace_id=str(event.trace_id))
                    await self.kernel._send_reply(
                        chat_id,
                        msg_failed,
                        platform=platform,
                    )
                    if bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False)):
                        bus_sim = getattr(self.kernel, "bus", None)
                        if bus_sim is not None:
                            with contextlib.suppress(Exception):
                                await bus_sim.publish(
                                    AdamiEvent(
                                        trace_id=str(event.trace_id),
                                        source_module="nexus.reply",
                                        target_topic="system.events",
                                        priority=EventPriority.NORMAL,
                                        payload={"event_type": "REPLY", "text": msg_failed},
                                    )
                    )
                    _decision_reward(str(event.trace_id), 0.0, {"error": "task_failed"})
                except asyncio.CancelledError:
                    episode_outcome = "cancelled"
                    try:
                        msg_cancelled = i18n_t(
                            "dp.queue.cancelled_reply",
                            locale=effective_locale,
                            trace_id=str(event.trace_id),
                        )
                        await self._send_reply_once_per_trace(
                            chat_id=chat_id,
                            trace_id=str(event.trace_id),
                            platform=platform,
                            text=msg_cancelled,
                            kind="cancelled",
                        )
                        if bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False)):
                            bus_sim = getattr(self.kernel, "bus", None)
                            if bus_sim is not None:
                                with contextlib.suppress(Exception):
                                    await bus_sim.publish(
                                        AdamiEvent(
                                            trace_id=str(event.trace_id),
                                            source_module="nexus.reply",
                                            target_topic="system.events",
                                            priority=EventPriority.NORMAL,
                                            payload={"event_type": "REPLY", "text": msg_cancelled},
                                        )
                                    )
                    except Exception:
                        pass
                    raise
                except Exception as e:
                    episode_outcome = "fatal"
                    await self._handle_fatal_error(e, task_text, event, chat_id)
                    _decision_reward(str(event.trace_id), 0.0, {"error": "fatal"})
                finally:
                    get_experience_sink().end_episode(eid, episode_outcome, pop_context=True)
                    if budget_token is not None:
                        with contextlib.suppress(Exception):
                            reset_task_timeout_budget(budget_token)
                    self._append_stop_audit_daily(task_text, chat_id, platform, str(event.trace_id))
                    self._write_session_export_log(
                        task_text, chat_id, platform, str(event.trace_id)
                    )
                    self._skip_lifecycle_done = False
                    await self._release_session_lock(chat_id)
            finally:
                reset_request_locale(loc_token)

    def _determine_platform(self, source_module: str) -> str:
        if source_module == "user.prompt":
            return "cli"
        elif source_module == "sensory.discord":
            return "discord"
        elif source_module == "sensory.telegram":
            return "telegram"
        return "telegram"

    async def _try_acquire_session_turn(self, chat_id: str, trace_id: str) -> bool:
        """Atomically take the per-chat session lock when it is free.

        ``LifecycleManager`` may run multiple ``process()`` coroutines concurrently
        (``ADAMI_EVENT_CONSUMER_MAX_CONCURRENT``).  A plain ``if session_lock.locked()``
        before a later ``acquire()`` is a TOCTOU race: two tasks can both see the
        session as free.  A per-chat *meta* lock serializes the check+acquire.
        """
        if chat_id not in self.kernel.session_locks:
            self.kernel.session_locks[chat_id] = asyncio.Lock()
        meta_map = getattr(self.kernel, "_dp_session_turn_meta_locks", None)
        if meta_map is None:
            self.kernel._dp_session_turn_meta_locks = {}  # type: ignore[attr-defined]
            meta_map = self.kernel._dp_session_turn_meta_locks
        if chat_id not in meta_map:
            meta_map[chat_id] = asyncio.Lock()
        meta = meta_map[chat_id]
        main = self.kernel.session_locks[chat_id]
        async with meta:
            if main.locked():
                return False
            await main.acquire()
            self.kernel.active_sessions[chat_id] = {
                "trace_id": trace_id,
                "started_at": time.time(),
            }
        return True

    async def _acquire_session_lock(self, chat_id: str, trace_id: str, platform: str) -> None:
        """Tests and legacy call sites: same as a session turn, with user-visible *busy* on failure."""
        ok = await self._try_acquire_session_turn(chat_id, trace_id)
        if not ok:
            await self.kernel._send_reply(
                chat_id, i18n_t("dp.session.busy"), platform=platform
            )
            raise asyncio.CancelledError("session locked")

    def _check_circuit_breaker(self, loop_depth: int, trace_id: str) -> None:
        if loop_depth > 3:
            console.print(
                "[bold red][Circuit Breaker] loop_depth limit reached; task aborted[/bold red]"
            )
            raise TaskFailedException(str(trace_id))

    def _handle_early_skill_creation(
        self, task_text: str, chat_id: str, platform: str, trace_id: str
    ) -> bool:
        if task_text and self.skill_router and self.skill_router.is_skill_creation_task(task_text):
            logger.info(_dcpu_t("dcpu.log.unified_skill_intent"))
            if hasattr(self.kernel, "planner") and self.kernel.planner:
                asyncio.create_task(
                    self._create_skill_via_planner(task_text, chat_id, platform, trace_id)
                )
                return True
        return False

    async def _create_skill_via_planner(
        self, task: str, chat_id: str, platform: str, trace_id: str
    ):
        with tracer.start_as_current_span(
            "decision_processor.create_skill_via_planner",
            trace_id=f"decision_processor_create_skill_{trace_id}",
            task_description=task,
            metadata={"chat_id": chat_id, "platform": platform},
        ):
            try:
                plan_result = await self.kernel.planner.plan_and_execute(
                    task=task,
                    trace_id=trace_id,
                    chat_id=int(chat_id) if chat_id.isdigit() else None,
                )

                # 【v2.8 核心防护】plan_result 可能为 None
                if plan_result is None:
                    logger.warning(_dcpu_t("dcpu.warn.planner_none"))
                    parsed = {}
                elif isinstance(plan_result, dict):
                    parsed = extract_json_from_llm_output(str(plan_result.get("text") or "")) or {}
                elif isinstance(plan_result, str):
                    # ==== 修复点：增加 or {}，确保即使 JSON 提取失败也赋予空字典 ====
                    parsed = extract_json_from_llm_output(plan_result) or {}
                else:
                    parsed = plan_result or {}

                # 【核心修复】增强 skill_name 提取
                skill_name = (
                    parsed.get("skill_name")
                    or parsed.get("name")
                    or (
                        self.skill_router.extract_normalized_skill_name(task)
                        if self.skill_router
                        else None
                    )
                    or (
                        "CRYPTO_PRICE_QUERY"
                        if task_matches_pipe_catalog(task, "dp.intent.pipe_crypto")
                        else None
                    )
                    or (
                        "WEATHER_QUERY"
                        if task_matches_pipe_catalog(task, "dp.intent.pipe_weather")
                        else None
                    )
                    or (
                        "TSUNAMI_ALERT_QUERY"
                        if task_matches_pipe_catalog(task, "dp.intent.pipe_tsunami")
                        else None
                    )
                    or re.sub(r"[^a-zA-Z0-9_]", "", task[:30]).upper()
                    or "TEMP_SKILL"
                )

                try:
                    validated = SkillCreationPlan.model_validate(
                        {**parsed, "skill_name": skill_name}
                    )
                    logger.info(_dcpu_t("dcpu.log.plan_ok", skill_name=validated.skill_name))
                    final_result = {
                        "skill_name": validated.skill_name,
                        "description": validated.description,
                        "status": validated.status,
                        "code": validated.code,
                    }
                    _decision_reward(
                        str(trace_id),
                        1.0,
                        {"status": "success"},
                        source="decision_processor.planner_skill",
                    )
                except ValidationError as ve:
                    logger.warning(_dcpu_t("dcpu.warn.plan_pydantic", ve=ve))
                    final_result = {
                        "skill_name": skill_name,
                        "description": task[:100],
                        "status": "fallback",
                        "code": "",
                    }
                    _decision_reward(
                        str(trace_id),
                        0.5,
                        {"status": "fallback"},
                        source="decision_processor.planner_skill",
                    )

                if platform == "cli":
                    plan_result = self._format_cli_result(final_result)
                await self.kernel._send_reply(
                    chat_id,
                    plan_result,
                    platform=platform,
                    trace_id=str(trace_id),
                workflow_id=None,
                    force_trace_footer=True,
                )

                if platform == "cli":
                    try:
                        console.print("\n[bold green]Erique@AdamI>[/bold green] ", end="")
                        sys.stdout.flush()
                        logger.debug(_dcpu_t("dcpu.debug.cli_after_skill"))
                    except Exception as e:
                        logger.warning(_dcpu_t("dcpu.warn.cli_print", e=e))

            except Exception as e:
                logger.error(_dcpu_t("dcpu.err.planner_skill", e=e))
                await self.kernel._send_reply(
                    chat_id,
                    i18n_t("dp.skill.create_user_fail", detail=str(e)),
                    platform=platform,
                )
                _decision_reward(
                    str(trace_id),
                    0.0,
                    {"status": "error"},
                    source="decision_processor.planner_skill",
                )
            finally:
                # 【v2.8 关键修复】无论成功失败都强制恢复 CLI 提示符
                if platform == "cli":
                    try:
                        console.print("\n[bold green]Erique@AdamI>[/bold green] ", end="")
                        sys.stdout.flush()
                        logger.debug(_dcpu_t("dcpu.debug.cli_planner_finally"))
                    except Exception as e:
                        logger.warning(_dcpu_t("dcpu.warn.cli_print", e=e))

    def _detect_multimodal_intent(self, payload: Dict) -> tuple:
        if payload.get("image_base64") or payload.get("media_type") in (
            "photo",
            "video",
            "video_note",
        ):
            return "ANALYZE_IMAGE", {"image_base64": payload.get("image_base64", "")}
        elif payload.get("file_path") or "document" in str(payload.get("task", "")).lower():
            return "PARSE_DOCUMENT", {"file_path": payload.get("file_path", "")}
        return None, None

    async def _dispatch_multimodal_task(
        self, action: str, args: Dict, chat_id: str, platform: str, trace_id: str, task_text: str
    ):
        await self._update_ui(
            chat_id, platform, i18n_t("dp.ui.multimodal_processing", action=action)
        )
        res = await self._execute_action(action, args, chat_id, platform, trace_id, task_text)

        if isinstance(res, dict) and res.get("type") == "raw_multi_modal":
            raw_content = res.get("raw_content", "")
            media_type = res.get("media_type", "")
            loc_raw = get_request_locale() or settings.effective_ui_default_locale() or ""
            loc_l = str(loc_raw).lower().replace("_", "-")
            locale_style = (
                i18n_t("dp.multimodal.locale_style_zh")
                if loc_l.startswith("zh")
                else i18n_t("dp.multimodal.locale_style_en")
            )
            analysis_prompt = i18n_t(
                "dp.multimodal.doc_analyst_prompt",
                locale_style=locale_style,
                content=raw_content[:4000],
            )
            summary = await self.kernel.router.call_llm(
                analysis_prompt,
                brain_type="action",
                temperature=0.3,
                apply_design_output_policy=True,
            )
            res = summary.strip()

            await self.kernel.memory.store_experience(
                trace_id,
                "code_ops",
                {"action": "TASK_COMPLETE", "result": res, "media_type": media_type},
                chat_id=chat_id,
            )

        await self.kernel._send_reply(chat_id, str(res), platform=platform)

    async def _dispatch_direct_answer(
        self, data: Any, task_text: str, chat_id: str, platform: str, trace_id: str
    ):
        content = (
            str(data).strip()
            if data and str(data).strip()
            else i18n_t("dp.direct_answer.fast_brain_default")
        )
        await self._send_reply_once_per_trace(
            chat_id=chat_id,
            trace_id=str(trace_id),
            platform=platform,
            text=content,
            kind="direct_answer",
            dedupe_task=task_text,
        )

    async def _maybe_route_intent_adaptive(
        self,
        task_text: str,
        chat_id: str,
        platform: str,
        trace_id: str,
        *,
        router_tag: str,
        router_data: Any,
        trace_span: Any = None,
    ) -> tuple[bool, Optional[Dict[str, Any]]]:
        """
        Tiered intent pipeline (Step 5): rules → optional LLM → template registry.
        Returns (True, None) when a user reply was sent and Planner must be skipped.
        Returns (False, meta_dict) on Planner fallback when the pipeline ran with a
        classification — ``meta_dict`` is optional ``intent_adaptive_meta`` (Step 7).
        Returns (False, None) when the pipeline is off, inapplicable, or has no classification.
        """
        if not bool(getattr(settings, "ADAMI_INTENT_ADAPTIVE_PIPELINE_ENABLED", False)):
            return False, None
        if router_tag != "COMPLEX_TASK":
            return False, None

        registry = getattr(self.kernel, "intent_template_registry", None)
        if registry is None:
            return False, None

        from adami_kernel.cortex.intent_adaptive.handoff_meta import (
            build_planner_handoff_meta,
            handoff_reason_for_planner_fallback,
        )
        from adami_kernel.cortex.intent_adaptive.llm_classifier import (
            maybe_llm_classify_with_settings,
        )
        from adami_kernel.cortex.intent_adaptive.rule_classifier import rule_classify_after_router
        from adami_kernel.cortex.intent_adaptive.telemetry import (
            record_intent_classification_on_span,
        )
        from adami_kernel.cortex.intent_adaptive.template_registry import TemplateExecutionContext

        rule = rule_classify_after_router(task_text, router_tag=router_tag, router_data=router_data)
        _llm_budget = max(
            1.0, float(getattr(settings, "ADAMI_INTENT_ADAPTIVE_LLM_PHASE_TIMEOUT_SEC", 15.0))
        )
        try:
            refined = await asyncio.wait_for(
                maybe_llm_classify_with_settings(
                    task_text,
                    router_tag=router_tag,
                    router_data=router_data,
                    rule_result=rule,
                    call_llm=self.kernel.router.call_llm,
                    settings=settings,
                ),
                timeout=_llm_budget,
            )
        except asyncio.TimeoutError:
            logger.warning(
                "[intent_adaptive] llm_classify phase exceeded %.2fs; using rule tier only",
                _llm_budget,
            )
            refined = None
        classification = refined if refined is not None else rule
        if classification is None:
            logger.debug("[intent_adaptive] no_classification")
            return False, None

        record_intent_classification_on_span(trace_span, classification)

        fam_val = (
            classification.primary_family.value
            if hasattr(classification.primary_family, "value")
            else str(classification.primary_family)
        )
        logger.debug(
            "[intent_adaptive] family=%s type=%s conf=%.3f route=%s",
            fam_val,
            classification.primary_type,
            float(classification.confidence),
            classification.route,
        )

        min_conf = float(settings.ADAMI_INTENT_CLASSIFIER_MIN_CONFIDENCE)
        loc_raw = get_request_locale() or settings.effective_ui_default_locale() or "en"

        async def _template_send_reply(c_id: str, text: str, p: str = "telegram") -> None:
            await self.kernel._send_reply(c_id, text, platform=p)

        toolbox = getattr(self.kernel, "toolbox", None)
        web_mod = getattr(toolbox, "web", None) if toolbox is not None else None
        web_search = None
        if web_mod is not None and callable(getattr(web_mod, "search", None)):

            async def _web_search(*args: object, **kwargs: object) -> object:
                return await web_mod.search(*args, **kwargs)

            web_search = _web_search

        ctx = TemplateExecutionContext(
            task_text=task_text,
            chat_id=str(chat_id),
            platform=platform,
            trace_id=str(trace_id),
            send_reply=_template_send_reply,
            router_call_llm=self.kernel.router.call_llm,
            web_search=web_search,
            classification=classification,
        )

        handler = await registry.resolve(classification)
        template_handoff_to_planner = False
        empty_template_body = False
        _tpl_timeout = max(
            1.0, float(getattr(settings, "ADAMI_INTENT_TEMPLATE_EXECUTE_TIMEOUT_SEC", 30.0))
        )
        _action_gate = bool(
            getattr(settings, "ADAMI_INTENT_ACTION_TEMPLATE_REQUIRES_CONFIRMATION", True)
        )
        _action_perm = bool(getattr(settings, "ADAMI_INTENT_ACTION_PERMISSION_GRANTED", False))
        _action_ack = isinstance(router_data, dict) and (
            router_data.get("intent_action_user_ack") is True
        )
        import adami_kernel.orchestrator.hitl_handler as _hitl_mod

        _hh = getattr(self.kernel, "hitl_handler", None) or _hitl_mod.hitl_handler
        _hitl_one_shot = (
            bool(_hh)
            and hasattr(_hh, "consume_intent_action_template_ack")
            and _hh.consume_intent_action_template_ack(str(chat_id))
        )
        _action_eff_ack = _action_perm or _action_ack or _hitl_one_shot
        if handler is not None and float(classification.confidence) >= min_conf:
            if (
                classification.primary_family == IntentFamily.ACTION
                and _action_gate
                and not _action_eff_ack
            ):
                _hitl_tg = bool(getattr(settings, "ADAMI_INTENT_ACTION_HITL_TELEGRAM", True))
                _sent_buttons = False
                if (
                    _hitl_tg
                    and _hh is not None
                    and getattr(_hh, "telegram_nerve", None) is not None
                    and str(platform).lower() == "telegram"
                ):
                    try:
                        await _hh.prompt_intent_action_template_confirmation(
                            str(chat_id), task_text
                        )
                        _sent_buttons = True
                    except Exception as e:
                        logger.warning("[intent_adaptive] ACTION HITL prompt failed: %s", e)
                if not _sent_buttons:
                    await self.kernel._send_reply(
                        chat_id,
                        i18n_t("intent.action_template.hitl_fallback_body", locale=loc_raw),
                        platform=platform,
                    )
                return True, None
            try:
                outcome = await asyncio.wait_for(handler.execute(ctx), timeout=_tpl_timeout)
            except asyncio.TimeoutError:
                logger.warning(
                    "[intent_adaptive] template execute timeout after %.2fs", _tpl_timeout
                )
                await self.kernel._send_reply(
                    chat_id,
                    i18n_t("intent.adaptive.template_execute_timeout", locale=loc_raw),
                    platform=platform,
                )
                return True, None
            if not outcome.handoff_to_dynamic:
                body = (outcome.reply_markdown or "").strip()
                if body:
                    await self.kernel._send_reply(
                        chat_id, outcome.reply_markdown, platform=platform
                    )
                    return True, None
                if classification.route == "clarify":
                    await self.kernel._send_reply(
                        chat_id,
                        i18n_t("intent.clarify.prompt", locale=loc_raw),
                        platform=platform,
                    )
                    return True, None
                empty_template_body = True
            else:
                template_handoff_to_planner = True

        if classification.route == "clarify" and float(classification.confidence) >= min_conf:
            await self.kernel._send_reply(
                chat_id,
                i18n_t("intent.clarify.prompt", locale=loc_raw),
                platform=platform,
            )
            return True, None

        if bool(getattr(settings, "ADAMI_INTENT_ADAPTIVE_FALLBACK_NOTICE", False)):
            await self.kernel._send_reply(
                chat_id,
                i18n_t("intent.adaptive.user.fallback_to_planner", locale=loc_raw),
                platform=platform,
            )

        reason = handoff_reason_for_planner_fallback(
            classification,
            handler=handler,
            min_confidence=min_conf,
            template_handoff_to_planner=template_handoff_to_planner,
            empty_template_body=empty_template_body,
        )
        meta = build_planner_handoff_meta(classification, handoff_reason=reason)
        logger.debug("[intent_adaptive_handoff] %s", meta)
        return False, meta

    async def _dispatch_complex_task(
        self,
        task_text: str,
        chat_id: str,
        platform: str,
        trace_id: str,
        *,
        router_data: Any = None,
        trace_span: Any = None,
    ) -> None:
        await self._update_ui(chat_id, platform, i18n_t("dp.ui.complex_planner"))
        handled, intent_adaptive_meta = await self._maybe_route_intent_adaptive(
            task_text,
            chat_id,
            platform,
            trace_id,
            router_tag="COMPLEX_TASK",
            router_data=router_data,
            trace_span=trace_span,
        )
        if handled:
            return
        if hasattr(self.kernel, "planner") and self.kernel.planner:
            plan_kw: dict[str, object] = {
                "task": task_text,
                "trace_id": trace_id,
                "chat_id": int(chat_id) if chat_id.isdigit() else None,
            }
            if intent_adaptive_meta is not None:
                plan_kw["intent_adaptive_meta"] = intent_adaptive_meta
            plan_result = await self.kernel.planner.plan_and_execute(**plan_kw)
            if platform == "cli":
                plan_result = self._format_cli_result(plan_result)
            wid = None
            plan_text = plan_result
            # Structured planner results can carry workflow_id explicitly to avoid text parsing.
            if isinstance(plan_result, dict):
                wid = str(plan_result.get("workflow_id") or "") or None
                if "text" in plan_result and isinstance(plan_result.get("text"), str):
                    plan_text = str(plan_result.get("text") or "")
            if looks_like_planner_scratchpad(plan_text):
                return
            await self.kernel._send_reply(
                chat_id,
                plan_text,
                platform=platform,
                trace_id=str(trace_id),
                workflow_id=wid,
                force_trace_footer=True,
            )

    async def _dispatch_slow_brain(
        self, task_text: str, event: AdamiEvent, chat_id: str, platform: str
    ):
        await self._update_ui(chat_id, platform, i18n_t("dp.ui.deep_reasoning"))

        recalled_errors = ""
        if self.episodic_memory and getattr(self.episodic_memory, "enabled", False):
            action_intent = str(event.payload.get("action", "THINK"))
            recalled_errors = await self.episodic_memory.recall_errors(task_text, action_intent)
            if recalled_errors:
                logger.info(_dcpu_t("dcpu.log.episodic_recalled", snippet=recalled_errors[:100]))

        history = await self.kernel.memory.retrieve_recent("code_ops", 4, chat_id=chat_id)
        semantics = await self.kernel.memory.retrieve_recent("semantic_rules", limit=10)
        semantic_text = (
            "\n".join([f"- {s.get('insight', '')}" for s in semantics])
            if semantics
            else i18n_t("dp.semantic.none")
        )
        self.kernel.prompt_builder.system_persona = (
            f"{self.kernel._get_current_persona()}\n\n"
            f"{i18n_t('dp.persona.semantic_rules_heading')}\n{semantic_text}"
        )

        prompt = await self.kernel.prompt_builder.build_action_prompt(
            event.payload, history, recalled_errors
        )
        brain_type = (
            "think" if event.priority in [EventPriority.HIGH, EventPriority.URGENT] else "action"
        )

        response = await self.kernel.router.call_llm(
            prompt,
            brain_type=brain_type,
            temperature=0.3,
            apply_design_output_policy=True,
        )
        action, args = self.kernel._parse_decision(response)

        console.print(f"\n[bold yellow]Slow path action: {action}[/bold yellow]")
        await self._update_ui(chat_id, platform, i18n_t("dp.ui.executing_action", action=action))

        res = await self._execute_action(action, args, chat_id, platform, event.trace_id, task_text)

        if res == "TASK_COMPLETE":
            done_locale = get_request_locale() or settings.effective_ui_default_locale()
            await self.kernel._send_reply(
                chat_id,
                i18n_t("dp.task.completed", trace_id=str(event.trace_id), locale=done_locale),
                platform=platform,
            )
            return

        if res and action != "THINK":
            console.print(
                f"[dim green]{i18n_t('dp.console.feedback_prefix')}{str(res)[:250]}...[/dim green]"
            )

        safe_res = self._safe_serialize(res)
        await self.kernel.memory.store_experience(
            event.trace_id,
            "code_ops",
            {"action": action, "result": safe_res, "task": task_text},
            chat_id=chat_id,
        )

        feedback_event = AdamiEvent(
            trace_id=event.trace_id,
            source_module="cortex.feedback",
            target_topic="system.events",
            priority=EventPriority.HIGH,
            payload={
                "task": task_text,
                "environment_feedback": safe_res or "ok",
                "loop_depth": event.payload.get("loop_depth", 0) + 1,
                "chat_id": chat_id,
            },
        )
        asyncio.create_task(self.kernel.bus.publish(feedback_event))

        if action != "THINK":
            await self.kernel._send_reply(chat_id, str(res), platform=platform)

    async def _handle_rate_limit(self, chat_id: str, platform: str, e: Exception):
        console.print(f"[bold red]API rate limit / exhaustion: {e}[/bold red]")
        if hasattr(self.kernel, "proprioception"):
            await self.kernel.proprioception.toggle_api_starvation(True)
        await asyncio.sleep(30)
        await self.kernel._send_reply(
            chat_id,
            i18n_t("dp.rate_limit.user"),
            platform=platform,
        )

    async def _handle_fatal_error(
        self, e: Exception, task_text: str, event: AdamiEvent, chat_id: str
    ):
        console.print(f"[bold red]Fatal error: {e}[/bold red]")
        logger.exception("DecisionProcessor fatal error")
        if self.episodic_memory:
            await self.episodic_memory.save_error(
                task=task_text,
                action=str(event.payload.get("action", "UNKNOWN")),
                bad_code=str(event.payload),
                error_msg=str(e),
            )
        error_event = AdamiEvent(
            trace_id=event.trace_id,
            source_module="cortex.feedback",
            target_topic="system.events",
            priority=EventPriority.HIGH,
            payload={
                "environment_feedback": str(e),
                "loop_depth": event.payload.get("loop_depth", 0) + 1,
                "chat_id": chat_id,
            },
        )
        asyncio.create_task(self.kernel.bus.publish(error_event))

    async def _release_session_lock(self, chat_id: str):
        lock = self.kernel.session_locks.get(chat_id)
        if lock and lock.locked():
            lock.release()
        self.kernel.active_sessions.pop(chat_id, None)
        # Clear cancel tracking for this chat (best-effort).
        try:
            tasks = getattr(self.kernel, "_chat_running_tasks", None)
            if isinstance(tasks, dict):
                cur = asyncio.current_task()
                if tasks.get(str(chat_id)) is cur or cur is None:
                    tasks.pop(str(chat_id), None)
        except Exception:
            pass
        tq = getattr(self.kernel, "task_queue", None)
        if tq is not None:
            try:
                tq.mark_finished(str(chat_id))
            except Exception:
                pass

        # Auto-dispatch next queued task (FIFO) for this chat.
        next_item = None
        if not bool(getattr(self.kernel, "_sim_disable_auto_dispatch", False)):
            if tq is not None:
                try:
                    next_item = tq.pop_next(str(chat_id))
                except Exception:
                    next_item = None
        if next_item is not None and getattr(self.kernel, "bus", None) is not None:
            try:
                qt_tid = str(getattr(next_item, "trace_id", "") or "").strip()
                nxt = AdamiEvent(
                    trace_id=(
                        qt_tid if qt_tid else f"cmd_q_{int(time.time() * 1000)}"
                    ),
                    source_module=str(next_item.source_module or "user.prompt"),
                    target_topic="system.events",
                    priority=EventPriority.HIGH,
                    payload={"task": next_item.task, "chat_id": str(chat_id)},
                )
                # In offline sim/capture/replay, run inline to avoid race conditions where the capture
                # thinks the queue drained before the dispatched task starts.
                if bool(getattr(settings, "ADAMI_SIM_OFFLINE", False)):
                    await self.process(nxt)
                else:
                    asyncio.create_task(self.kernel.bus.publish(nxt))
            except Exception:
                pass

        is_background = bool(
            os.environ.get("INVOCATION_ID")
            or os.environ.get("SYSTEMD_EXEC_PID")
            or not sys.stdout.isatty()
        )
        if not is_background:
            try:
                console.print("\n[bold green]Erique@AdamI>[/bold green] ", end="")
                sys.stdout.flush()
                logger.debug(_dcpu_t("dcpu.debug.cli_release"))
            except Exception as e:
                logger.warning(_dcpu_t("dcpu.warn.cli_print_release", e=e))
        else:
            logger.debug(_dcpu_t("dcpu.debug.cli_bg_silent"))

    async def _handle_maintain_action(self, chat_id: str, platform: str):
        """只读 PARA / 候选池诊断（不修改任何文件）。"""
        await self._update_ui(chat_id, platform, i18n_t("dp.ui.scanning_second_brain"))
        sb = getattr(self.kernel, "second_brain", None)
        root = (
            Path(sb.root).resolve()
            if sb is not None
            else Path(settings.path_second_brain_root).resolve()
        )
        para_dirs = SecondBrainManager.PARA_MEMBER_DIRS

        lines: list[str] = [
            i18n_t("dp.maintain.title"),
            "",
            i18n_t("dp.maintain.root_line", root=str(root)),
            "",
            i18n_t("dp.maintain.para_heading"),
        ]

        inbox_md = 0
        for name in para_dirs:
            d = root / name
            if not d.is_dir():
                lines.append(i18n_t("dp.maintain.dir_missing", name=name))
                continue
            n_md = 0
            try:
                for p in d.iterdir():
                    if p.is_file() and p.suffix.lower() == ".md" and p.name != "README.md":
                        n_md += 1
            except OSError as e:
                lines.append(i18n_t("dp.maintain.list_dir_fail", name=name, detail=str(e)))
                continue
            if name == "Inbox":
                inbox_md = n_md

            readme = d / "README.md"
            if not readme.is_file():
                rstat = i18n_t("dp.maintain.readme_missing")
            else:
                try:
                    rtext = readme.read_text(encoding="utf-8").strip()
                    if len(rtext) < 12:
                        rstat = i18n_t("dp.maintain.readme_short")
                    else:
                        rstat = i18n_t("dp.maintain.readme_ok")
                except OSError as e:
                    rstat = i18n_t("dp.maintain.readme_unreadable", detail=str(e))

            lines.append(i18n_t("dp.maintain.para_line", name=name, n_md=str(n_md), rstat=rstat))

        lines.append("")
        if inbox_md > 20:
            lines.append(i18n_t("dp.maintain.inbox_high", n=str(inbox_md)))
        elif inbox_md > 5:
            lines.append(i18n_t("dp.maintain.inbox_mid", n=str(inbox_md)))
        else:
            lines.append(i18n_t("dp.maintain.inbox_low", n=str(inbox_md)))

        cand = root / "System" / "working-memory" / "candidates.md"
        lines.append("")
        lines.append(i18n_t("dp.maintain.candidates_heading"))
        if not cand.is_file():
            lines.append(i18n_t("dp.maintain.candidates_missing"))
        else:
            try:
                raw = cand.read_text(encoding="utf-8")
                total = len(raw.splitlines())
                nonempty = sum(1 for ln in raw.splitlines() if ln.strip())
                lines.append(
                    i18n_t(
                        "dp.maintain.candidates_stats",
                        total=str(total),
                        nonempty=str(nonempty),
                    )
                )
            except OSError as e:
                lines.append(i18n_t("dp.maintain.candidates_read_fail", detail=str(e)))

        lines.append("")
        lines.append(i18n_t("dp.maintain.footer"))

        report = "\n".join(lines)
        logger.info(_dcpu_t("dcpu.log.maintain_done", root=root, inbox_md=inbox_md))
        await self.kernel._send_reply(chat_id, report, platform)

    async def _handle_writing_action(self, task_text: str, chat_id: str, platform: str):
        """先读 Resources 下写作相关 .md，再调用 LLM 生成正文（不写回磁盘）。"""
        await self._update_ui(chat_id, platform, i18n_t("dp.ui.reading_resources_writing"))
        sb = getattr(self.kernel, "second_brain", None)
        root = (
            Path(sb.root).resolve()
            if sb is not None
            else Path(settings.path_second_brain_root).resolve()
        )
        res_dir = root / "Resources"

        m = re.match(
            rf"^(/writing|{_WRITING_CMD_ZH})\s*([\s\S]*)$",
            (task_text or "").strip(),
            re.IGNORECASE,
        )
        user_instruction = ((m.group(2) or "") if m else (task_text or "")).strip()
        user_instruction = user_instruction.lstrip("：: ").strip()
        if not user_instruction:
            user_instruction = i18n_t("dp.writing.default_instruction")

        _WRITING_MAX_TOTAL = 12000
        _WRITING_MAX_PER_FILE = 6000
        _WRITING_FALLBACK_N = 5

        blocks: list[str] = []
        used_files: list[str] = []
        total_chars = 0

        if not res_dir.is_dir():
            await self.kernel._send_reply(
                chat_id,
                i18n_t("dp.resources.missing_dir", n=_WRITING_FALLBACK_N),
                platform,
            )
            return

        writing_matches: list[Path] = []
        fallback_md: list[Path] = []
        try:
            for p in sorted(res_dir.iterdir()):
                if not p.is_file() or p.suffix.lower() != ".md" or p.name == "README.md":
                    continue
                fallback_md.append(p)
                if "writing" in p.stem.lower():
                    writing_matches.append(p)
        except OSError as e:
            logger.warning(_dcpu_t("dcpu.warn.writing_list", e=e))
            await self.kernel._send_reply(
                chat_id, i18n_t("dp.resources.read_fail", detail=str(e)), platform
            )
            return

        candidates = writing_matches if writing_matches else fallback_md[:_WRITING_FALLBACK_N]

        for p in candidates:
            if total_chars >= _WRITING_MAX_TOTAL:
                break
            try:
                raw = p.read_text(encoding="utf-8")
            except OSError as e:
                logger.warning(_dcpu_t("dcpu.warn.writing_skip", path=p, e=e))
                continue
            chunk = raw.strip()
            if len(chunk) > _WRITING_MAX_PER_FILE:
                chunk = chunk[:_WRITING_MAX_PER_FILE] + i18n_t("dp.writing.chunk_truncated")
            blocks.append(i18n_t("dp.writing.resource_block", name=p.name, chunk=chunk))
            used_files.append(p.name)
            total_chars += len(chunk)

        resource_section = (
            "\n\n---\n\n".join(blocks) if blocks else i18n_t("dp.writing.no_resources_body")
        )

        prompt = (
            i18n_t("dp.writing.prompt_intro")
            + "\n\n"
            + i18n_t("dp.writing.prompt_user_heading")
            + user_instruction
            + "\n\n"
            + i18n_t("dp.writing.prompt_resources_heading")
            + resource_section
            + "\n\n"
            + i18n_t("dp.writing.prompt_outro")
        )

        mode = "writing_glob" if writing_matches else "fallback_first_md"
        logger.info(
            _dcpu_t(
                "dcpu.log.writing_mode",
                mode=mode,
                files=str(used_files),
                chars=total_chars,
            )
        )

        try:
            response = await self.kernel.router.call_llm(
                prompt,
                brain_type="action",
                temperature=0.35,
                max_tokens=4096,
                apply_design_output_policy=True,
            )
        except Exception as e:
            logger.error(_dcpu_t("dcpu.err.writing_llm", e=e), exc_info=True)
            await self.kernel._send_reply(
                chat_id, i18n_t("dp.writing.gen_fail", detail=str(e)), platform=platform
            )
            return

        body = (response or "").strip()
        cite = (
            ", ".join(f"`{n}`" for n in used_files)
            if used_files
            else i18n_t("dp.writing.cite_none")
        )
        header = i18n_t("dp.writing.header_line", cite=cite, mode=mode)
        await self.kernel._send_reply(chat_id, header + body, platform)

    async def _handle_task_note_action(self, task_text: str, chat_id: str, platform: str):
        """TASK_NOTE：解析正文并追加到 System/working-memory/tasks.md「## 待办」段。"""
        await self._update_ui(chat_id, platform, i18n_t("dp.ui.writing_task_pool"))
        body = extract_task_note_body(task_text or "")
        body_one = re.sub(r"\s+", " ", body).strip()
        if not body_one:
            await self.kernel._send_reply(
                chat_id,
                i18n_t("dp.task_note.empty_body"),
                platform,
            )
            return
        if len(body_one) > 500:
            body_one = body_one[:499] + "…"

        from datetime import datetime

        date_s = datetime.now().strftime("%Y-%m-%d")
        sb = getattr(self.kernel, "second_brain", None)
        root = (
            Path(sb.root).resolve()
            if sb is not None
            else Path(settings.path_second_brain_root).resolve()
        )
        tasks_path = root / "System" / "working-memory" / "tasks.md"
        template = i18n_t("dp.tasks_md.template")
        try:
            tasks_path.parent.mkdir(parents=True, exist_ok=True)
            if tasks_path.is_file():
                content = tasks_path.read_text(encoding="utf-8")
            else:
                content = template
            new_content = append_checkbox_under_todo_section(content, body_one, date_s)
            tasks_path.write_text(new_content, encoding="utf-8")
        except OSError as e:
            logger.error(_dcpu_t("dcpu.err.task_note_write", e=e), exc_info=True)
            await self.kernel._send_reply(
                chat_id, i18n_t("dp.tasks_md.write_fail", detail=str(e)), platform
            )
            return

        logger.info(
            _dcpu_t(
                "dcpu.log.task_note_ok",
                path=str(tasks_path),
                date=date_s,
                preview=body_one[:120],
            ),
        )
        await self.kernel._send_reply(
            chat_id,
            i18n_t("dp.task_note.saved", body=body_one, date=date_s),
            platform,
        )

    async def _handle_digest_action(self, chat_id: str, platform: str):
        import os

        cand_path = settings.path_brain_candidates_md
        if not os.path.exists(cand_path):
            await self.kernel._send_reply(chat_id, i18n_t("dp.digest.no_candidates_file"), platform)
            return
        with open(cand_path, "r", encoding="utf-8") as f:
            content = f.read()
        items = [line for line in content.splitlines() if line.startswith("- 🟢")]
        if not items:
            await self.kernel._send_reply(chat_id, i18n_t("dp.digest.pool_empty"), platform)
            return
        text_to_send = i18n_t("dp.digest.prompt", items="\n".join(items))
        if platform == "telegram" and self.kernel.telegram_nerve:
            buttons = [
                {
                    "text": i18n_t("port.digest.btn_approve_all"),
                    "callback_data": "digest:approve_all",
                },
                {
                    "text": i18n_t("port.digest.btn_reject_all"),
                    "callback_data": "digest:reject_all",
                },
            ]
            await self.kernel.telegram_nerve.send_interactive_buttons(
                int(chat_id), text_to_send, buttons
            )
        else:
            await self.kernel._send_reply(
                chat_id,
                text_to_send + i18n_t("dp.digest.cli_footer"),
                platform,
            )

    async def _handle_intake_action(
        self, task: str, chat_id: str, platform: str, payload: Optional[Dict[str, Any]] = None
    ):
        from adami_kernel.integration.sim.dp_offline_scenarios import try_handle_offline_intake

        if await try_handle_offline_intake(self, task, chat_id, platform, payload):
            return

        await self._update_ui(chat_id, platform, i18n_t("dp.ui.distilling_metadata"))
        unc = i18n_t("dp.intake.uncategorized_summary")
        archive_body, source_stem = await _intake_archive_body_from_payload(
            task, payload or {}, self.kernel
        )
        if source_stem:
            logger.info(_dcpu_t("dcpu.log.intake_markdown", file=source_stem))
        prompt = (
            i18n_t("dp.intake.prompt_intro")
            + archive_body[:4000]
            + i18n_t("dp.intake.prompt_rules")
            + i18n_t("dp.intake.prompt_example_json")
            + i18n_t("dp.intake.prompt_footer")
        )
        try:
            response = await self.kernel.router.call_llm(
                prompt, brain_type="action", temperature=0.0, max_tokens=800
            )
            meta = extract_json_from_llm_output(response) or {
                "domain": "misc",
                "type": "note",
                "tags": [],
                "summary": unc,
                "suggested_para": "inbox",
            }
            para_key = _normalize_intake_suggested_para(meta)
            from datetime import datetime

            sb = getattr(self.kernel, "second_brain", None)
            brain_root = (
                Path(sb.root) if sb is not None else Path(settings.path_second_brain_root).resolve()
            )

            fm_src = ""
            if source_stem:
                fm_src = (
                    f"source_file: '{_yaml_single_quoted(source_stem)}'\n"
                    f"body_format: markdown\n"
                )
            yaml_header = (
                f"---\npara: inbox\n{fm_src}"
                f"domain: {meta.get('domain', 'misc')}\n"
                f"type: {meta.get('type', 'note')}\ntags: {meta.get('tags', [])}\n"
                f"summary: '{meta.get('summary', unc)}'\n---\n\n"
            )
            filename = f"note_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
            inbox_dir = brain_root / "Inbox"
            inbox_dir.mkdir(parents=True, exist_ok=True)
            filepath = inbox_dir / filename
            filepath.write_text(yaml_header + archive_body, encoding="utf-8")

            final_rel = f"Inbox/{filename}"
            move_note = ""
            if para_key != "inbox":
                dest_fn = _safe_intake_md_filename(
                    meta.get("suggested_filename") or meta.get("target_filename"),
                    filename,
                )
                try:
                    move_mgr = sb if sb is not None else SecondBrainManager(str(brain_root))
                    new_path = move_mgr.move_brain_note(filepath, para_key, dest_fn)
                    final_rel = str(new_path.resolve().relative_to(brain_root.resolve())).replace(
                        "\\", "/"
                    )
                except (ValueError, OSError) as move_err:
                    logger.warning(_dcpu_t("dcpu.warn.intake_para", e=move_err))
                    move_note = i18n_t(
                        "dp.intake.move_failed_note",
                        para_key=para_key,
                        detail=str(move_err),
                    )

            if sb is not None and hasattr(sb, "sync_para_readme_members"):
                try:
                    sb.sync_para_readme_members()
                except Exception as sync_err:
                    logger.warning(_dcpu_t("dcpu.warn.intake_readme", e=sync_err))
            reply = i18n_t(
                "dp.intake.reply_ok",
                path=final_rel,
                tags=str(meta.get("tags", [])),
                summary=str(meta.get("summary", unc)),
                para_key=para_key,
                move_note=move_note,
            )
            await self.kernel._send_reply(chat_id, reply, platform)
            logger.info(
                _dcpu_t(
                    "dcpu.log.intake_ok",
                    path=final_rel,
                    domain=meta.get("domain"),
                    para=para_key,
                ),
            )
        except Exception as e:
            logger.error(_dcpu_t("dcpu.err.intake", e=e))
            await self.kernel._send_reply(
                chat_id, i18n_t("dp.intake.archive_fail", detail=str(e)), platform
            )

    async def _handle_force_optimize_action(self, skill_name: str, chat_id: str, platform: str):
        await self._update_ui(
            chat_id, platform, i18n_t("dp.ui.force_optimize_skill", skill_name=skill_name)
        )
        if not hasattr(self.kernel, "skill_optimizer") or not self.kernel.skill_optimizer:
            await self.kernel._send_reply(
                chat_id, i18n_t("dp.optimize.optimizer_missing"), platform
            )
            return
        try:
            result = await self.kernel.skill_optimizer.optimize(skill_name)
            if result.get("status") == "skipped":
                reply = i18n_t("dp.optimize.skipped_instinct", name=skill_name)
            elif result.get("status") == "success":
                reply = i18n_t(
                    "dp.optimize.success",
                    name=skill_name,
                    version=result.get("new_version", "v1.1"),
                )
            else:
                reply = i18n_t(
                    "dp.optimize.unknown",
                    name=skill_name,
                    reason=result.get("reason") or i18n_t("dp.optimize.reason_unknown"),
                )
            await self.kernel._send_reply(chat_id, reply, platform)
            logger.info(_dcpu_t("dcpu.log.force_opt_ok", skill_name=skill_name))
        except Exception as e:
            logger.error(_dcpu_t("dcpu.err.force_opt", e=e))
            await self.kernel._send_reply(
                chat_id, i18n_t("dp.optimize.fail", name=skill_name, detail=str(e)), platform
            )


# --- END OF FILE src/adami_kernel/cortex/decision_processor.py ---
# 文件路径：src/adami_kernel/cortex/decision_processor.py
