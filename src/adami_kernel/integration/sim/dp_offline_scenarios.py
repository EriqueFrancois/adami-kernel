"""Offline sim scenarios previously inlined in DecisionProcessor.process."""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

from adami_kernel.config import settings
from adami_kernel.cortex.decision_processor_support import TaskFailedException
from adami_kernel.i18n import t as i18n_t
from adami_kernel.nexus.event import AdamiEvent, EventPriority


async def try_handle_offline_sim(
    dp: Any,
    event: Any,
    task_text: str,
    chat_id: str,
    platform: str,
    effective_locale: str,
) -> bool:
    if not bool(getattr(settings, "ADAMI_SIM_OFFLINE", False)):
        return False

    # Sim offline: deterministic "multi-turn + tool choice" scenario for replay runner.
    if bool(getattr(settings, "ADAMI_SIM_OFFLINE", False)) and task_text.lower().startswith(
        "/toolchoice"
    ):
        bus = getattr(dp.kernel, "bus", None)

        async def _emit_sim(payload2: dict) -> None:
            if not bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False)):
                return
            if bus is None:
                return
            try:
                await bus.publish(
                    AdamiEvent(
                        trace_id=str(event.trace_id),
                        source_module="orchestrator.toolchoice",
                        target_topic="system.events",
                        priority=EventPriority.NORMAL,
                        payload=payload2,
                    )
                )
            except Exception:
                return

        await _emit_sim({"event_type": "TOOLCHOICE_START"})
        t1 = await dp.kernel.router.call_llm(
            "choose a tool for: demo", brain_type="think", timeout_sec=2.0
        )
        t2 = await dp.kernel.router.call_llm(
            "execute chosen tool", brain_type="action", timeout_sec=2.0
        )
        rows = await dp.kernel.toolbox.web_search(
            "adami kernel",
            max_results=3,
            trace_id=str(event.trace_id),
            timeout_sec=2.0,
        )
        # Simulated MCP external tool call path.
        async def _ext_echo(message: str = "") -> dict:
            return {"message": str(message)}

        dp.kernel.toolbox.register_external_tools(
            "mcp:sim",
            tools=[
                {
                    "name": "MCP_ECHO",
                    "description": "Simulated MCP external echo tool (offline)",
                    "json_schema": {
                        "type": "object",
                        "properties": {"message": {"type": "string"}},
                        "required": ["message"],
                    },
                }
            ],
            executors={"MCP_ECHO": _ext_echo},
        )
        ext = await dp.kernel.toolbox.execute_tool(
            "MCP_ECHO",
            {"message": "hello"},
            trace_id=str(event.trace_id),
            timeout_sec=2.0,
        )
        msg = f"toolchoice ok: llm1={t1[:24]!r} llm2={t2[:24]!r} web={len(rows)} ext={str(ext)[:32]}"
        await dp.kernel._send_reply(chat_id, msg, platform=platform)
        await _emit_sim({"event_type": "REPLY", "text": msg})
        await _emit_sim({"event_type": "TOOLCHOICE_DONE"})
        return True
    # Sim offline: Milestone A queue/lifecycle scenarios (deterministic, no external deps).
    if bool(getattr(settings, "ADAMI_SIM_OFFLINE", False)):
        raw_lower = task_text.lower().strip()
        tq_sim = getattr(dp.kernel, "task_queue", None)
        bus_sim = getattr(dp.kernel, "bus", None)

        if raw_lower.startswith("/queue status"):
            pending_n = 0
            in_progress = False
            try:
                pending_n = len(tq_sim.list_pending(chat_id)) if tq_sim is not None else 0
                in_progress = (
                    tq_sim.get_in_progress(chat_id) is not None if tq_sim is not None else False
                )
            except Exception:
                pending_n = 0
                in_progress = False
            await dp.kernel._send_reply(
                chat_id,
                f"✅ Queue status: pending={pending_n} in_progress={1 if in_progress else 0}",
                platform=platform,
            )
            if bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False)) and bus_sim is not None:
                try:
                    await bus_sim.publish(
                        AdamiEvent(
                            trace_id=str(event.trace_id),
                            source_module="orchestrator.queue_sim",
                            target_topic="system.events",
                            priority=EventPriority.NORMAL,
                            payload={
                                "event_type": "REPLY",
                                "text": f"✅ Queue status: pending={pending_n} in_progress={1 if in_progress else 0}",
                            },
                        )
                    )
                except Exception:
                    pass
            return True

        if raw_lower.startswith("/queue discard"):
            dropped = 0
            had_ip = False
            try:
                if tq_sim is not None:
                    dropped, had_ip = tq_sim.discard_all(chat_id)
            except Exception:
                dropped, had_ip = 0, False
            await dp.kernel._send_reply(
                chat_id,
                f"✅ Queue discarded: pending_dropped={int(dropped)} in_progress_dropped={1 if had_ip else 0}",
                platform=platform,
            )
            if bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False)) and bus_sim is not None:
                try:
                    await bus_sim.publish(
                        AdamiEvent(
                            trace_id=str(event.trace_id),
                            source_module="orchestrator.queue_sim",
                            target_topic="system.events",
                            priority=EventPriority.NORMAL,
                            payload={
                                "event_type": "REPLY",
                                "text": f"✅ Queue discarded: pending_dropped={int(dropped)} in_progress_dropped={1 if had_ip else 0}",
                            },
                        )
                    )
                except Exception:
                    pass
            return True

        if raw_lower.startswith("/queue_timeout_flow"):
            # Publish a second task while the session is locked to force enqueue + busy_queued UX,
            # then exceed hard-timeout so the session is released and the queued task continues.
            async def _publish_queued() -> None:
                try:
                    await asyncio.sleep(0.05)
                    # Run through DP concurrently so it hits the "busy → enqueue" path even when
                    # the capture consumer is single-threaded.
                    await dp.process(
                        AdamiEvent(
                            trace_id=f"{str(event.trace_id)}.queued",
                            source_module=str(event.source_module),
                            target_topic="system.events",
                            priority=EventPriority.HIGH,
                            payload={"task": "/queued_after_timeout", "chat_id": chat_id},
                        )
                    )
                except Exception:
                    return

            asyncio.create_task(_publish_queued())
            # Trigger the hard-timeout handler deterministically (independent of configured timeout).
            await asyncio.sleep(0.2)
            raise asyncio.TimeoutError("simulated hard-timeout (queue_timeout_flow)")

        if raw_lower.startswith("/queued_after_timeout"):
            msg_t = i18n_t(
                "dp.queue.continued_reply",
                locale=effective_locale,
                trace_id=str(event.trace_id),
            )
            await dp.kernel._send_reply(chat_id, msg_t, platform=platform)
            if (
                bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False))
                and bus_sim is not None
            ):
                with contextlib.suppress(Exception):
                    await bus_sim.publish(
                        AdamiEvent(
                            trace_id=str(event.trace_id),
                            source_module="orchestrator.queue_sim",
                            target_topic="system.events",
                            priority=EventPriority.NORMAL,
                            payload={"event_type": "REPLY", "text": msg_t},
                        )
                    )
            return True

        if raw_lower.startswith("/queue_cancel_active_flow"):
            # Deterministic cancellation scenario:
            # - While this task holds the session lock, enqueue a follow-up task
            # - Then request cancellation via `/queue cancel`
            # - The cancellation handler will release the session so the queued task can continue.
            async def _enqueue_followup() -> None:
                try:
                    await asyncio.sleep(0.05)
                    await dp.process(
                        AdamiEvent(
                            trace_id=f"{str(event.trace_id)}.queued",
                            source_module=str(event.source_module),
                            target_topic="system.events",
                            priority=EventPriority.HIGH,
                            payload={"task": "/queued_after_cancel", "chat_id": chat_id},
                        )
                    )
                except Exception:
                    return

            async def _request_cancel() -> None:
                try:
                    await asyncio.sleep(0.12)
                    await dp.process(
                        AdamiEvent(
                            trace_id=f"{str(event.trace_id)}.cancel",
                            source_module=str(event.source_module),
                            target_topic="system.events",
                            priority=EventPriority.HIGH,
                            payload={"task": "/queue cancel", "chat_id": chat_id},
                        )
                    )
                except Exception:
                    return

            asyncio.create_task(_enqueue_followup())
            asyncio.create_task(_request_cancel())
            # Wait until cancelled. This await is the explicit cancellation point.
            await asyncio.sleep(30.0)
            return True

        if raw_lower.startswith("/queued_after_cancel"):
            msg2 = i18n_t(
                "dp.queue.continued_reply",
                locale=effective_locale,
                trace_id=str(event.trace_id),
            )
            await dp.kernel._send_reply(chat_id, msg2, platform=platform)
            if bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False)) and bus_sim is not None:
                with contextlib.suppress(Exception):
                    await bus_sim.publish(
                        AdamiEvent(
                            trace_id=str(event.trace_id),
                            source_module="orchestrator.queue_sim",
                            target_topic="system.events",
                            priority=EventPriority.NORMAL,
                            payload={"event_type": "REPLY", "text": msg2},
                        )
                    )
            return True

        if raw_lower.startswith("/queue_failed_flow"):
            # Deterministic failure scenario:
            # - While this task holds the session lock, enqueue a follow-up task
            # - Then fail the current task in a controlled way (TaskFailedException),
            #   releasing the session so the queued task can continue.
            async def _enqueue_after_fail() -> None:
                try:
                    await asyncio.sleep(0.05)
                    await dp.process(
                        AdamiEvent(
                            trace_id=f"{str(event.trace_id)}.queued",
                            source_module=str(event.source_module),
                            target_topic="system.events",
                            priority=EventPriority.HIGH,
                            payload={"task": "/queued_after_fail", "chat_id": chat_id},
                        )
                    )
                except Exception:
                    return

            asyncio.create_task(_enqueue_after_fail())
            await asyncio.sleep(0.2)
            raise TaskFailedException("simulated task failure (queue_failed_flow)")

        if raw_lower.startswith("/queued_after_fail"):
            msg3 = i18n_t(
                "dp.queue.continued_reply",
                locale=effective_locale,
                trace_id=str(event.trace_id),
            )
            await dp.kernel._send_reply(chat_id, msg3, platform=platform)
            if (
                bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False))
                and bus_sim is not None
            ):
                with contextlib.suppress(Exception):
                    await bus_sim.publish(
                        AdamiEvent(
                            trace_id=str(event.trace_id),
                            source_module="orchestrator.queue_sim",
                            target_topic="system.events",
                            priority=EventPriority.NORMAL,
                            payload={"event_type": "REPLY", "text": msg3},
                        )
                    )
            return True

        if raw_lower.startswith("/queue_budget_exceeded_flow"):
            # Deterministic budget-exceeded scenario:
            # - While this task holds the session lock, enqueue a follow-up task
            # - Then raise BudgetExceededError (simulating "no remaining budget to start tools")
            # - The handler should release the session so the queued task can continue.
            from adami_kernel.observability.timeout_budget import BudgetExceededError

            async def _enqueue_after_budget() -> None:
                try:
                    await asyncio.sleep(0.05)
                    await dp.process(
                        AdamiEvent(
                            trace_id=f"{str(event.trace_id)}.queued",
                            source_module=str(event.source_module),
                            target_topic="system.events",
                            priority=EventPriority.HIGH,
                            payload={"task": "/queued_after_budget", "chat_id": chat_id},
                        )
                    )
                except Exception:
                    return

            asyncio.create_task(_enqueue_after_budget())
            await asyncio.sleep(0.2)
            raise BudgetExceededError("simulated budget exceeded (queue_budget_exceeded_flow)")

        if raw_lower.startswith("/queued_after_budget"):
            msg_b = i18n_t(
                "dp.queue.continued_reply",
                locale=effective_locale,
                trace_id=str(event.trace_id),
            )
            await dp.kernel._send_reply(chat_id, msg_b, platform=platform)
            if (
                bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False))
                and bus_sim is not None
            ):
                with contextlib.suppress(Exception):
                    await bus_sim.publish(
                        AdamiEvent(
                            trace_id=str(event.trace_id),
                            source_module="orchestrator.queue_sim",
                            target_topic="system.events",
                            priority=EventPriority.NORMAL,
                            payload={"event_type": "REPLY", "text": msg_b},
                        )
                    )
            return True

        if raw_lower.startswith("/reply_dedupe_filler_flow"):
            # Gate: for a single prompt (one trace_id), a fallback reply must be sent at most once.
            msg_a = i18n_t("dp.sim.fallback_reply_a", locale=effective_locale)
            msg_b = i18n_t("dp.sim.fallback_reply_b", locale=effective_locale)
            sent_a = await dp._send_reply_once_per_trace(
                chat_id=chat_id,
                trace_id=str(event.trace_id),
                platform=platform,
                text=msg_a,
                kind="fallback",
            )
            _ = await dp._send_reply_once_per_trace(
                chat_id=chat_id,
                trace_id=str(event.trace_id),
                platform=platform,
                text=msg_b,
                kind="fallback",
            )
            if bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False)) and bus_sim is not None:
                # Export only what was actually sent, as REPLY records.
                if sent_a:
                    with contextlib.suppress(Exception):
                        await bus_sim.publish(
                            AdamiEvent(
                                trace_id=str(event.trace_id),
                                source_module="nexus.reply",
                                target_topic="system.events",
                                priority=EventPriority.NORMAL,
                                payload={"event_type": "REPLY", "text": msg_a},
                            )
                        )
            return True

    if bool(getattr(settings, "ADAMI_SIM_OFFLINE", False)) and (
        task_text.lower().startswith("/planner_multistep")
        or task_text.lower().startswith("/planner_multistep_mcp")
    ):
        bus = getattr(dp.kernel, "bus", None)

        async def _emit_sim(payload2: dict) -> None:
            if not bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False)):
                return
            if bus is None:
                return
            try:
                await bus.publish(
                    AdamiEvent(
                        trace_id=str(event.trace_id),
                        source_module="orchestrator.planner_sim",
                        target_topic="system.events",
                        priority=EventPriority.NORMAL,
                        payload=payload2,
                    )
                )
            except Exception:
                return

        await _emit_sim({"event_type": "PLANNER_START"})

        # Multi-turn context: two LLM calls (think -> action) before the first tool attempt.
        t1 = await dp.kernel.router.call_llm(
            "plan a 2-step tool workflow", brain_type="think", timeout_sec=2.0
        )
        prefer_mcp = task_text.lower().startswith("/planner_multistep_mcp")
        branch_prompt = (
            f"choose_branch: prefer external tool MCP_FLAKY based on plan: {t1[:64]}"
            if prefer_mcp
            else f"choose_branch: decide between MCP_FLAKY vs execute_command based on plan: {t1[:64]}"
        )
        t2 = await dp.kernel.router.call_llm(
            branch_prompt,
            brain_type="action",
            timeout_sec=2.0,
        )

        # Dynamic tool selection + retry: external tool fails first time, then succeeds.
        state = {"n": 0}

        async def _flaky(op: str = "ping") -> dict:
            state["n"] += 1
            if state["n"] == 1:
                raise RuntimeError("simulated transient failure")
            return {"ok": True, "op": str(op), "attempt": int(state["n"])}

        dp.kernel.toolbox.register_external_tools(
            "mcp:sim",
            tools=[
                {
                    "name": "MCP_FLAKY",
                    "description": "Simulated flaky external tool (fails once, then succeeds)",
                    "json_schema": {
                        "type": "object",
                        "properties": {"op": {"type": "string"}},
                        "required": ["op"],
                    },
                }
            ],
            executors={"MCP_FLAKY": _flaky},
        )

        branch = "mcp_flaky"
        if isinstance(t2, str) and "execute_command" in t2.lower():
            branch = "execute_command"
        await _emit_sim({"event_type": "BRANCH_DECISION", "branch": branch, "llm_action": str(t2)[:120]})

        if branch == "execute_command":
            # Tool path A: local command tool call (no retry needed).
            res_cmd = await dp.kernel.toolbox.execute_command(
                "echo planner_branch_ok",
                timeout=2.0,
                trace_id=str(event.trace_id),
            )
            # Keep reply stable across capture (real echo has newline) and replay (mocked stdout may differ).
            _ = res_cmd
            msg2 = "✅ Planner multistep done"
            await dp.kernel._send_reply(chat_id, msg2, platform=platform)
            await _emit_sim({"event_type": "REPLY", "text": msg2})
            await _emit_sim({"event_type": "PLANNER_DONE"})
            return True

        # Tool path B: MCP flaky tool (fails once, then retry).
        try:
            await dp.kernel.toolbox.execute_tool(
                "MCP_FLAKY",
                {"op": "ping"},
                trace_id=str(event.trace_id),
                timeout_sec=2.0,
            )
        except Exception:
            await _emit_sim({"event_type": "ROLLBACK", "reason": "tool_error", "tool": "MCP_FLAKY"})
            msg1 = "⚠️ Tool failed. Retry with smaller scope or increase timeout."
            await dp.kernel._send_reply(chat_id, msg1, platform=platform)
            await _emit_sim({"event_type": "REPLY", "text": msg1})

        # LLM decides retry strategy (mocked in replay).
        _ = await dp.kernel.router.call_llm(
            f"retry strategy based on action: {t2[:64]}",
            brain_type="think",
            timeout_sec=2.0,
        )
        res = await dp.kernel.toolbox.execute_tool(
            "MCP_FLAKY",
            {"op": "ping"},
            trace_id=str(event.trace_id),
            timeout_sec=2.0,
        )

        msg2 = f"✅ Planner multistep done: {str(res)[:80]}"
        await dp.kernel._send_reply(chat_id, msg2, platform=platform)
        await _emit_sim({"event_type": "REPLY", "text": msg2})
        await _emit_sim({"event_type": "PLANNER_DONE"})
        return True
    return False


async def try_handle_offline_intake(
    dp: Any,
    task: str,
    chat_id: str,
    platform: str,
    payload: Any = None,
) -> bool:
    if not bool(getattr(settings, "ADAMI_SIM_OFFLINE", False)):
        return False
    from datetime import datetime
    from pathlib import Path as P

    async def _emit_sim(payload2: dict) -> None:
        if not bool(getattr(settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", False)):
            return
        bus = getattr(dp.kernel, "bus", None)
        if bus is None:
            return
        try:
            ev2 = AdamiEvent(
                trace_id=str(
                    getattr(dp.kernel, "active_sessions", {}).get(chat_id, {}).get("trace_id")
                    or "sim_intake"
                ),
                source_module="orchestrator.intake",
                target_topic="system.events",
                priority=EventPriority.NORMAL,
                payload=payload2,
            )
            await bus.publish(ev2)
        except Exception:
            return

    await _emit_sim({"event_type": "INTAKE_START"})
    sb = getattr(dp.kernel, "second_brain", None)
    brain_root = (
        P(sb.root) if sb is not None else P(settings.path_second_brain_root).resolve()
    )
    inbox_dir = brain_root / "Inbox"
    inbox_dir.mkdir(parents=True, exist_ok=True)
    filename = f"intake_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    fp = inbox_dir / filename
    body = (task or "").strip()
    fp.write_text(body + "\n", encoding="utf-8")
    rel = f"Inbox/{filename}"
    await _emit_sim({"event_type": "INTAKE_DONE", "note_path": rel, "tags": ["intake"]})
    msg = f"✅ Saved to SecondBrain: {rel}"
    await dp.kernel._send_reply(chat_id, msg, platform)
    await _emit_sim({"event_type": "REPLY", "text": msg})
    return True
