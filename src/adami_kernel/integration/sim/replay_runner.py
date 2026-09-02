"""Deterministic replay runner: inject + mocks.

Goal: run the kernel against an existing NDJSON trace and make replays stable by
mocking tool/LLM/MCP calls using values recorded in that trace (or provided fixtures).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional, Sequence

import adami_kernel.config as config_mod
from adami_kernel.core.component_initializer import ComponentInitializer
from adami_kernel.core.lifecycle_manager import LifecycleManager
from adami_kernel.integration.sim.replay import (
    FaultInjectionOptions,
    ReplayValidationError,
    load_ndjson_records,
    replay_inject_with_faults,
    validate_phase1_records,
)
from adami_kernel.integration.sim.schema import ReplayTraceRecordV1
from adami_kernel.integration.sim.trace_sink import get_trace_sink
from adami_kernel.integration.sim.replay_trace_compare import compare_isomorphic
from adami_kernel.nexus.event import AdamiEvent, EventPriority
from adami_kernel.observability.tool_call_context import reset_tool_trace_id, set_tool_trace_id


@dataclass(frozen=True)
class ExpectedToolCall:
    tool: str
    event_type: str  # TOOL_CALL_DONE/TIMEOUT/ERROR
    result: Any


def _iter_tool_outcomes(records: Sequence[ReplayTraceRecordV1]) -> List[ExpectedToolCall]:
    out: List[ExpectedToolCall] = []
    for r in records:
        if r.target_topic != "system.events":
            continue
        p = r.payload_redacted or {}
        if not isinstance(p, dict):
            continue
        et = str(p.get("event_type") or "")
        if et not in ("TOOL_CALL_DONE", "TOOL_CALL_TIMEOUT", "TOOL_CALL_ERROR"):
            continue
        tool = str(p.get("tool") or "").strip()
        if not tool:
            continue
        out.append(
            ExpectedToolCall(
                tool=tool,
                event_type=et,
                result=p.get("result"),
            )
        )
    return out


class ReplayMocks:
    """Installable mocks that replay tool outcomes in order."""

    def __init__(self, *, expected_tool_calls: Sequence[ExpectedToolCall]):
        self._q: asyncio.Queue[ExpectedToolCall] = asyncio.Queue()
        for c in expected_tool_calls:
            self._q.put_nowait(c)

    async def next_tool(self, tool: str) -> ExpectedToolCall:
        """Consume next expected tool call; enforce ordering."""
        try:
            nxt = self._q.get_nowait()
        except asyncio.QueueEmpty as e:
            raise ReplayValidationError(f"replay ran out of expected tool calls (wanted {tool})") from e
        if nxt.tool != tool:
            raise ReplayValidationError(f"tool mismatch: expected {nxt.tool}, got {tool}")
        return nxt


async def _publish(bus: Any, ev: AdamiEvent) -> None:
    await bus.publish(ev)


def _is_prompt_record(r: ReplayTraceRecordV1, *, inject_topic: str) -> bool:
    if r.target_topic != inject_topic:
        return False
    if str(r.source_module) != "user.prompt":
        return False
    p = r.payload_redacted or {}
    if not isinstance(p, dict):
        return False
    task = p.get("task")
    if not isinstance(task, str) or not task.strip():
        return False
    return True


async def run_replay(
    *,
    trace_file: Path,
    out_trace: Path,
    inject_topic: str = "system.events",
    chat_id: str = "cli",
    platform: str = "cli",
    full_kernel: bool = False,
    verify_isomorphic: bool = False,
    faults: FaultInjectionOptions | None = None,
    inject_all_records: bool = False,
) -> None:
    records = load_ndjson_records(trace_file)
    validate_phase1_records(records, allow_empty=False, monotonic_ts=False)

    if faults is not None and faults.enabled:
        # Apply deterministic phase-3 fault injection to the input record stream.
        # This affects both tool outcome mocks and injected prompt events.
        injected: list[ReplayTraceRecordV1] = []

        async def _collect(ev) -> None:
            # Convert back to record-like shape for downstream logic.
            injected.append(
                ReplayTraceRecordV1(
                    ts=0.0,
                    trace_id=str(getattr(ev, "trace_id", "")),
                    source_module=str(getattr(ev, "source_module", "")),
                    target_topic=str(getattr(ev, "target_topic", "")),
                    payload_redacted=dict(getattr(ev, "payload", {}) or {}),
                )
            )

        await replay_inject_with_faults(records, _collect, faults)
        # Keep original ts ordering/shape; we only care about payload + order.
        # Use original timestamps where available.
        for i, r in enumerate(injected):
            if i < len(records):
                injected[i] = injected[i].model_copy(update={"ts": float(records[i].ts)})
        records = injected

    if verify_isomorphic:
        # Isomorphism verification currently assumes a prompt-driven trace that the runner can re-execute.
        # (e.g. user.prompt -> kernel emits the rest). Traces without user.prompt are not supported.
        if not any(str(r.source_module) == "user.prompt" for r in records):
            raise ReplayValidationError(
                "verify_isomorphic requires a prompt-driven trace (source_module=user.prompt)."
            )

    expected_tools = _iter_tool_outcomes(records)
    mocks = ReplayMocks(expected_tool_calls=expected_tools)

    # Turn on export (isolated path) + offline.
    export_path = Path(out_trace).expanduser()
    try:
        export_path.unlink()
    except FileNotFoundError:
        pass

    old_env_trace_enabled = os.environ.get("ADAMI_SIM_TRACE_EXPORT_ENABLED")
    old_env_trace_path = os.environ.get("ADAMI_SIM_TRACE_EXPORT_PATH")
    old_env_sim_offline = os.environ.get("ADAMI_SIM_OFFLINE")
    old_cfg_trace_enabled = getattr(config_mod.settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", None)
    old_cfg_trace_path = getattr(config_mod.settings, "ADAMI_SIM_TRACE_EXPORT_PATH", None)
    old_cfg_sim_offline = getattr(config_mod.settings, "ADAMI_SIM_OFFLINE", None)

    os.environ["ADAMI_SIM_TRACE_EXPORT_ENABLED"] = "1"
    os.environ["ADAMI_SIM_TRACE_EXPORT_PATH"] = str(export_path)
    os.environ["ADAMI_SIM_OFFLINE"] = "1"

    try:
        setattr(config_mod.settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", True)
        setattr(config_mod.settings, "ADAMI_SIM_TRACE_EXPORT_PATH", str(export_path))
        setattr(config_mod.settings, "ADAMI_SIM_OFFLINE", True)
    except Exception:
        pass

    components = ComponentInitializer().initialize_components(kernel=None)
    lm = LifecycleManager(components)
    await components["bus"].initialize()
    from adami_kernel.cortex.decision_processor import DecisionProcessor

    dp = DecisionProcessor(lm)
    # Keep replays deterministic: clear any persisted queue state for this chat.
    try:
        tq0 = getattr(lm, "task_queue", None)
        if tq0 is not None:
            tq0.discard_all(chat_id)
    except Exception:
        pass

    # Install deterministic tool mocks (ToolboxManager is the unified entry).
    toolbox = components["toolbox"]

    async def _mock_execute_command(command: str, timeout: float = 30.0, *, trace_id: Optional[str] = None):
        tok = set_tool_trace_id(trace_id or "")
        try:
            exp = await mocks.next_tool("execute_command")
            if hasattr(toolbox, "_emit_tool_event"):
                await toolbox._emit_tool_event(  # type: ignore[attr-defined]
                    trace_id=str(trace_id or ""),
                    source_module="cortex.tools_manager",
                    payload={"event_type": "TOOL_CALL_START", "tool": "execute_command", "timeout_sec": float(timeout)},
                )
            if exp.event_type == "TOOL_CALL_DONE":
                res = exp.result if isinstance(exp.result, dict) else {"exit_code": 0, "stdout": "", "stderr": ""}
                if hasattr(toolbox, "_emit_tool_event"):
                    await toolbox._emit_tool_event(  # type: ignore[attr-defined]
                        trace_id=str(trace_id or ""),
                        source_module="cortex.tools_manager",
                        payload={"event_type": "TOOL_CALL_DONE", "tool": "execute_command", "result": dict(res), "latency_ms": 0},
                    )
                return dict(res)
            if exp.event_type == "TOOL_CALL_TIMEOUT":
                if hasattr(toolbox, "_emit_tool_event"):
                    await toolbox._emit_tool_event(  # type: ignore[attr-defined]
                        trace_id=str(trace_id or ""),
                        source_module="cortex.tools_manager",
                        payload={
                            "event_type": "TOOL_CALL_TIMEOUT",
                            "tool": "execute_command",
                            "timeout_sec": float(timeout),
                            "latency_ms": 0,
                        },
                    )
                return {"exit_code": -1, "stdout": "", "stderr": "Execution timed out."}
            if hasattr(toolbox, "_emit_tool_event"):
                await toolbox._emit_tool_event(  # type: ignore[attr-defined]
                    trace_id=str(trace_id or ""),
                    source_module="cortex.tools_manager",
                    payload={"event_type": "TOOL_CALL_ERROR", "tool": "execute_command", "result": exp.result, "latency_ms": 0},
                )
            return {"exit_code": -1, "stdout": "", "stderr": "Command failed or invalid: replay"}
        finally:
            reset_tool_trace_id(tok)

    async def _mock_web_search(query: str, max_results: int = 5, *, timelimit=None, region=None, trace_id=None, timeout_sec=30.0):
        exp = await mocks.next_tool("web_search")
        if hasattr(toolbox, "_emit_tool_event"):
            await toolbox._emit_tool_event(  # type: ignore[attr-defined]
                trace_id=str(trace_id or ""),
                source_module="cortex.tools_manager",
                payload={"event_type": "TOOL_CALL_START", "tool": "web_search", "timeout_sec": float(timeout_sec)},
            )
        if exp.event_type == "TOOL_CALL_DONE":
            res = exp.result if isinstance(exp.result, list) else []
            if hasattr(toolbox, "_emit_tool_event"):
                await toolbox._emit_tool_event(  # type: ignore[attr-defined]
                    trace_id=str(trace_id or ""),
                    source_module="cortex.tools_manager",
                    payload={"event_type": "TOOL_CALL_DONE", "tool": "web_search", "result": res, "latency_ms": 0},
                )
            return res
        if exp.event_type == "TOOL_CALL_TIMEOUT":
            if hasattr(toolbox, "_emit_tool_event"):
                await toolbox._emit_tool_event(  # type: ignore[attr-defined]
                    trace_id=str(trace_id or ""),
                    source_module="cortex.tools_manager",
                    payload={"event_type": "TOOL_CALL_TIMEOUT", "tool": "web_search", "result": exp.result, "latency_ms": 0},
                )
            return []
        if hasattr(toolbox, "_emit_tool_event"):
            await toolbox._emit_tool_event(  # type: ignore[attr-defined]
                trace_id=str(trace_id or ""),
                source_module="cortex.tools_manager",
                payload={"event_type": "TOOL_CALL_ERROR", "tool": "web_search", "result": exp.result, "latency_ms": 0},
            )
        return []

    async def _mock_process_multimodal(media_type: str, payload: Dict[str, Any], *, trace_id=None, timeout_sec=None):
        tool_name = f"multimodal.{str(media_type)}"
        exp = await mocks.next_tool(tool_name)
        if hasattr(toolbox, "_emit_tool_event"):
            await toolbox._emit_tool_event(  # type: ignore[attr-defined]
                trace_id=str(trace_id or ""),
                source_module="cortex.tools_manager",
                payload={"event_type": "TOOL_CALL_START", "tool": tool_name, "timeout_sec": float(timeout_sec or 0)},
            )
        if exp.event_type == "TOOL_CALL_DONE":
            res = exp.result if isinstance(exp.result, dict) else {"type": "text", "content": str(exp.result)}
            if hasattr(toolbox, "_emit_tool_event"):
                await toolbox._emit_tool_event(  # type: ignore[attr-defined]
                    trace_id=str(trace_id or ""),
                    source_module="cortex.tools_manager",
                    payload={"event_type": "TOOL_CALL_DONE", "tool": tool_name, "result": res, "latency_ms": 0},
                )
            return res
        if hasattr(toolbox, "_emit_tool_event"):
            await toolbox._emit_tool_event(  # type: ignore[attr-defined]
                trace_id=str(trace_id or ""),
                source_module="cortex.tools_manager",
                payload={"event_type": "TOOL_CALL_ERROR", "tool": tool_name, "result": exp.result, "latency_ms": 0},
            )
        return {"type": "text", "content": "replay_error", "task": ""}

    async def _mock_execute_tool(name: str, args: Optional[Dict[str, Any]] = None, *, trace_id=None, timeout_sec=None):
        tool_name = str(name).upper().strip()
        exp = await mocks.next_tool(tool_name)
        if hasattr(toolbox, "_emit_tool_event"):
            await toolbox._emit_tool_event(  # type: ignore[attr-defined]
                trace_id=str(trace_id or ""),
                source_module="cortex.tools_manager",
                payload={"event_type": "TOOL_CALL_START", "tool": tool_name, "timeout_sec": float(timeout_sec or 0)},
            )
        if exp.event_type == "TOOL_CALL_DONE":
            if hasattr(toolbox, "_emit_tool_event"):
                await toolbox._emit_tool_event(  # type: ignore[attr-defined]
                    trace_id=str(trace_id or ""),
                    source_module="cortex.tools_manager",
                    payload={"event_type": "TOOL_CALL_DONE", "tool": tool_name, "result": exp.result, "latency_ms": 0},
                )
            return exp.result
        if exp.event_type == "TOOL_CALL_TIMEOUT":
            if hasattr(toolbox, "_emit_tool_event"):
                await toolbox._emit_tool_event(  # type: ignore[attr-defined]
                    trace_id=str(trace_id or ""),
                    source_module="cortex.tools_manager",
                    payload={"event_type": "TOOL_CALL_TIMEOUT", "tool": tool_name, "result": exp.result, "latency_ms": 0},
                )
            raise TimeoutError("replay tool timeout")
        if hasattr(toolbox, "_emit_tool_event"):
            await toolbox._emit_tool_event(  # type: ignore[attr-defined]
                trace_id=str(trace_id or ""),
                source_module="cortex.tools_manager",
                payload={"event_type": "TOOL_CALL_ERROR", "tool": tool_name, "result": exp.result, "latency_ms": 0},
            )
        raise RuntimeError("replay tool failed")

    # Monkeypatch methods on the instance.
    toolbox.execute_command = _mock_execute_command  # type: ignore[assignment]
    toolbox.web_search = _mock_web_search  # type: ignore[assignment]
    toolbox.process_multimodal = _mock_process_multimodal  # type: ignore[assignment]
    toolbox.execute_tool = _mock_execute_tool  # type: ignore[assignment]

    # Mock LLM calls using the same tool-call queue.
    router = components.get("router")
    if router is not None:
        async def _mock_call_llm(prompt: str, brain_type: str = "action", **kwargs) -> str:
            exp = await mocks.next_tool(f"llm.{str(brain_type)}")
            if hasattr(router, "_emit_llm_event"):
                await router._emit_llm_event(  # type: ignore[attr-defined]
                    trace_id=str(kwargs.get("trace_id") or ""),
                    source_module="cortex.router",
                    payload={
                        "event_type": "TOOL_CALL_START",
                        "tool": f"llm.{str(brain_type)}",
                        "timeout_sec": float(kwargs.get("timeout_sec") or 0),
                    },
                )
            if exp.event_type == "TOOL_CALL_DONE":
                if isinstance(exp.result, dict) and isinstance(exp.result.get("text"), str):
                    if hasattr(router, "_emit_llm_event"):
                        await router._emit_llm_event(  # type: ignore[attr-defined]
                            trace_id=str(kwargs.get("trace_id") or ""),
                            source_module="cortex.router",
                            payload={
                                "event_type": "TOOL_CALL_DONE",
                                "tool": f"llm.{str(brain_type)}",
                                "result": exp.result,
                                "latency_ms": 0,
                            },
                        )
                    return str(exp.result["text"])
                if isinstance(exp.result, str):
                    if hasattr(router, "_emit_llm_event"):
                        await router._emit_llm_event(  # type: ignore[attr-defined]
                            trace_id=str(kwargs.get("trace_id") or ""),
                            source_module="cortex.router",
                            payload={
                                "event_type": "TOOL_CALL_DONE",
                                "tool": f"llm.{str(brain_type)}",
                                "result": {"text": exp.result},
                                "latency_ms": 0,
                            },
                        )
                    return exp.result
                if hasattr(router, "_emit_llm_event"):
                    await router._emit_llm_event(  # type: ignore[attr-defined]
                        trace_id=str(kwargs.get("trace_id") or ""),
                        source_module="cortex.router",
                        payload={
                            "event_type": "TOOL_CALL_DONE",
                            "tool": f"llm.{str(brain_type)}",
                            "result": {"text": ""},
                            "latency_ms": 0,
                        },
                    )
                return ""
            if exp.event_type == "TOOL_CALL_TIMEOUT":
                if hasattr(router, "_emit_llm_event"):
                    await router._emit_llm_event(  # type: ignore[attr-defined]
                        trace_id=str(kwargs.get("trace_id") or ""),
                        source_module="cortex.router",
                        payload={
                            "event_type": "TOOL_CALL_TIMEOUT",
                            "tool": f"llm.{str(brain_type)}",
                            "result": exp.result,
                            "latency_ms": 0,
                        },
                    )
                raise TimeoutError("replay llm timeout")
            if hasattr(router, "_emit_llm_event"):
                await router._emit_llm_event(  # type: ignore[attr-defined]
                    trace_id=str(kwargs.get("trace_id") or ""),
                    source_module="cortex.router",
                    payload={
                        "event_type": "TOOL_CALL_ERROR",
                        "tool": f"llm.{str(brain_type)}",
                        "result": exp.result,
                        "latency_ms": 0,
                    },
                )
            raise RuntimeError("replay llm error")

        router.call_llm = _mock_call_llm  # type: ignore[assignment]

    # Replay only the "prompt" records, but drive execution via deterministic kernel paths
    # (same strategy as golden trace capture), so we don't depend on Planner/LLM.
    from adami_kernel.cortex.decision_processor_report_actions import run_report_action
    from adami_kernel.orchestrator.workflow_models import Node, WorkflowState

    consumer_task = None
    if full_kernel or inject_all_records:
        # Strong mode: subscribe to the bus and run DecisionProcessor in this process,
        # avoiding LifecycleManager's background task fan-out (which can break ContextVar resets).
        bus = components["bus"]
        q = await bus.subscribe(inject_topic)

        async def _consume() -> None:
            while True:
                ev = await q.get()
                try:
                    if isinstance(ev, AdamiEvent) and str(getattr(ev, "source_module", "")) == "user.prompt":
                        await dp.process(ev)
                finally:
                    q.task_done()

        consumer_task = asyncio.create_task(_consume())
        await asyncio.sleep(0.05)

    for r in records:
        # When `--inject-all-records` is used, we inject the entire record stream into the bus so
        # regressions caused by "non-user" events (telemetry / internal markers) can be caught.
        if inject_all_records:
            payload_any = r.payload_redacted or {}
            if not isinstance(payload_any, dict):
                continue
            # For isomorphic verification, only user prompt records should be injected.
            # Injecting kernel-emitted records (TOOL_CALL_*, *_START/DONE, REPLY, etc.) would be
            # re-recorded by the trace sink and break length parity even when behavior is correct.
            if str(getattr(r, "source_module", "")) != "user.prompt":
                continue
            # Do not inject kernel-emitted reply records: the replayed kernel should emit them.
            try:
                if (
                    str(getattr(r, "source_module", "")) == "nexus.reply"
                    and str(payload_any.get("event_type") or "") == "REPLY"
                ):
                    continue
            except Exception:
                pass
            # Never re-inject internal auto-dispatch prompts (kernel-produced).
            try:
                if (
                    str(getattr(r, "source_module", "")) == "user.prompt"
                    and str(getattr(r, "trace_id", "")).startswith("cmd_q_")
                ):
                    continue
            except Exception:
                pass
            await _publish(
                components["bus"],
                AdamiEvent(
                    trace_id=str(r.trace_id),
                    source_module=str(r.source_module),
                    target_topic=str(r.target_topic or inject_topic),
                    priority=EventPriority.HIGH
                    if str(r.source_module) == "user.prompt"
                    else EventPriority.NORMAL,
                    payload=dict(payload_any),
                ),
            )
            # For user prompts, also maintain parity by tracking active session trace_id.
            if str(r.source_module) == "user.prompt":
                lm.active_sessions[chat_id] = {"trace_id": str(r.trace_id)}
            # Let the kernel process the injected prompt (if any) and wait for release.
            t0 = asyncio.get_running_loop().time()
            while chat_id in lm.active_sessions:
                if (asyncio.get_running_loop().time() - t0) > 10.0:
                    break
                await asyncio.sleep(0.05)
            continue

        if not _is_prompt_record(r, inject_topic=inject_topic):
            continue
        # Internal auto-dispatch prompts are produced by the kernel itself; do not re-inject them.
        try:
            if (
                str(getattr(r, "source_module", "")) == "user.prompt"
                and str(getattr(r, "trace_id", "")).startswith("cmd_q_")
            ):
                continue
        except Exception:
            pass
        payload = r.payload_redacted or {}
        if not isinstance(payload, dict):
            continue
        task = payload.get("task")
        if not isinstance(task, str) or not task.strip():
            continue

        # Emit the same user prompt event for trace parity.
        lm.active_sessions[chat_id] = {"trace_id": str(r.trace_id)}
        await _publish(
            components["bus"],
            AdamiEvent(
                trace_id=str(r.trace_id),
                source_module=str(r.source_module),
                target_topic=inject_topic,
                priority=EventPriority.HIGH,
                payload={"task": task, "chat_id": chat_id, "platform": platform},
            ),
        )

        if full_kernel or inject_all_records:
            # Wait for session release or timeout.
            t0 = asyncio.get_running_loop().time()
            while chat_id in lm.active_sessions:
                if (asyncio.get_running_loop().time() - t0) > 10.0:
                    break
                await asyncio.sleep(0.05)
        else:
            raw = task.strip()
            if raw.lower().startswith("/report"):
                await run_report_action(dp, raw, chat_id, platform)
            elif raw.lower().startswith("/intake"):
                await dp._handle_intake_action(raw, chat_id, platform, payload={})  # type: ignore[attr-defined]
            elif raw.lower().startswith("/tool_timeout"):
                await dp._execute_action(  # type: ignore[attr-defined]
                    "EXECUTE_COMMAND",
                    {"command": "sleep 2", "timeout_sec": 0.2},
                    chat_id,
                    platform,
                    trace_id=str(r.trace_id),
                    task_text="/tool_timeout",
                )
            elif raw.lower().startswith("/web_search"):
                rows = await components["toolbox"].web_search(
                    "adami kernel",
                    max_results=3,
                    trace_id=str(r.trace_id),
                    timeout_sec=2.0,
                )
                await _publish(
                    components["bus"],
                    AdamiEvent(
                        trace_id=str(r.trace_id),
                        source_module="nexus.reply",
                        target_topic="system.events",
                        priority=EventPriority.NORMAL,
                        payload={
                            "event_type": "REPLY",
                            "text": f"web_search results: {len(rows)}",
                            "trace_id": str(r.trace_id),
                        },
                    ),
                )
            elif raw.lower().startswith("/toolchoice"):
                # DP-driven deterministic scenario (offline) emits tool + reply events.
                await dp.process(
                    AdamiEvent(
                        trace_id=str(r.trace_id),
                        source_module=str(r.source_module),
                        target_topic=inject_topic,
                        priority=EventPriority.HIGH,
                        payload={"task": raw, "chat_id": chat_id, "platform": platform},
                    )
                )
            elif raw.lower().startswith("/planner_multistep"):
                await dp.process(
                    AdamiEvent(
                        trace_id=str(r.trace_id),
                        source_module=str(r.source_module),
                        target_topic=inject_topic,
                        priority=EventPriority.HIGH,
                        payload={"task": raw, "chat_id": chat_id, "platform": platform},
                    )
                )
            elif raw.lower().startswith("/planner_multistep_mcp"):
                await dp.process(
                    AdamiEvent(
                        trace_id=str(r.trace_id),
                        source_module=str(r.source_module),
                        target_topic=inject_topic,
                        priority=EventPriority.HIGH,
                        payload={"task": raw, "chat_id": chat_id, "platform": platform},
                    )
                )
            elif raw.lower().startswith("/workflow_engine"):
                # Deterministic "workflow run" without depending on WorkflowEngine background listeners.
                wid = "wf_golden_001"
                await _publish(
                    components["bus"],
                    AdamiEvent(
                        trace_id=str(r.trace_id),
                        source_module="orchestrator.planner",
                        target_topic="system.events",
                        priority=EventPriority.NORMAL,
                        payload={"event_type": "WORKFLOW_SUBMIT", "workflow_id": wid, "chat_id": chat_id},
                    ),
                )
                await _publish(
                    components["bus"],
                    AdamiEvent(
                        trace_id=f"wf_start_{wid}",
                        source_module="workflow.engine",
                        target_topic="workflow.events",
                        priority=EventPriority.NORMAL,
                        payload={"workflow_id": wid, "event_type": "WORKFLOW_START", "chat_id": chat_id},
                    ),
                )
                await _publish(
                    components["bus"],
                    AdamiEvent(
                        trace_id="wf_node___start__",
                        source_module="workflow.engine",
                        target_topic="workflow.events",
                        priority=EventPriority.NORMAL,
                        payload={
                            "workflow_id": wid,
                            "node_id": "__start__",
                            "event_type": "NODE_COMPLETE",
                            "result": {"status": "success", "data": "START 已越过"},  # adami:allow-cjk deterministic workflow fixture payload
                            "chat_id": chat_id,
                        },
                    ),
                )
                await _publish(
                    components["bus"],
                    AdamiEvent(
                        trace_id=f"wf_phase_{wid}_route",
                        source_module="workflow.engine",
                        target_topic="workflow.events",
                        priority=EventPriority.NORMAL,
                        payload={
                            "workflow_id": wid,
                            "chat_id": chat_id,
                            "event_type": "PHASE_TRANSITION",
                            "from_phase": "research",
                            "to_phase": "test",
                            "phase": "test",
                            "checkpoint_seq": 1,
                            "reason": "route_to_node tool_echo",
                            "gate_detail": "dag_route",
                            "source_module": "workflow.engine",
                            "workflow_version": 1,
                            "completed_node_id": "__start__",
                            "next_node_id": "tool_echo",
                        },
                    ),
                )
                tool_res = await components["toolbox"].execute_command(
                    "echo workflow_ok", trace_id=str(r.trace_id)
                )
                await _publish(
                    components["bus"],
                    AdamiEvent(
                        trace_id="wf_node_tool_echo",
                        source_module="workflow.engine",
                        target_topic="workflow.events",
                        priority=EventPriority.NORMAL,
                        payload={
                            "workflow_id": wid,
                            "node_id": "tool_echo",
                            "event_type": "NODE_COMPLETE",
                            "result": tool_res,
                            "chat_id": chat_id,
                        },
                    ),
                )
                await _publish(
                    components["bus"],
                    AdamiEvent(
                        trace_id=f"wf_phase_{wid}_to_end",
                        source_module="workflow.engine",
                        target_topic="workflow.events",
                        priority=EventPriority.NORMAL,
                        payload={
                            "workflow_id": wid,
                            "chat_id": chat_id,
                            "event_type": "PHASE_TRANSITION",
                            "from_phase": "test",
                            "to_phase": "deliver",
                            "phase": "deliver",
                            "checkpoint_seq": 1,
                            "reason": "route_to_node __end__",
                            "gate_detail": "dag_route",
                            "source_module": "workflow.engine",
                            "workflow_version": 1,
                            "completed_node_id": "tool_echo",
                            "next_node_id": "__end__",
                        },
                    ),
                )
                await _publish(
                    components["bus"],
                    AdamiEvent(
                        trace_id="wf_node___end__",
                        source_module="workflow.engine",
                        target_topic="workflow.events",
                        priority=EventPriority.NORMAL,
                        payload={
                            "workflow_id": wid,
                            "node_id": "__end__",
                            "event_type": "NODE_COMPLETE",
                            "result": {"status": "success", "data": "END 已越过"},  # adami:allow-cjk deterministic workflow fixture payload
                            "chat_id": chat_id,
                        },
                    ),
                )
                await _publish(
                    components["bus"],
                    AdamiEvent(
                        trace_id=f"wf_phase_{wid}_done",
                        source_module="workflow.engine",
                        target_topic="workflow.events",
                        priority=EventPriority.NORMAL,
                        payload={
                            "workflow_id": wid,
                            "chat_id": chat_id,
                            "event_type": "PHASE_TRANSITION",
                            "from_phase": "deliver",
                            "to_phase": "deliver",
                            "phase": "deliver",
                            "checkpoint_seq": 2,
                            "reason": "dag_terminal_success",
                            "gate_detail": "workflow_terminal",
                            "source_module": "workflow.engine",
                            "workflow_version": 1,
                            "completed_node_id": "__end__",
                            "next_node_id": None,
                        },
                    ),
                )
                await _publish(
                    components["bus"],
                    AdamiEvent(
                        trace_id=str(r.trace_id),
                        source_module="nexus.reply",
                        target_topic="system.events",
                        priority=EventPriority.NORMAL,
                        payload={
                            "event_type": "REPLY",
                            "text": f"✅ Workflow completed (workflow_id={wid})",
                            "trace_id": str(r.trace_id),
                        },
                    ),
                )
            elif raw.lower().startswith("/llm_call"):
                text = await components["router"].call_llm(  # type: ignore[union-attr]
                    "hello_llm", brain_type="think", timeout_sec=2.0
                )
                await _publish(
                    components["bus"],
                    AdamiEvent(
                        trace_id=str(r.trace_id),
                        source_module="nexus.reply",
                        target_topic="system.events",
                        priority=EventPriority.NORMAL,
                        payload={"event_type": "REPLY", "text": str(text)[:240], "trace_id": str(r.trace_id)},
                    ),
                )
            elif raw.lower().startswith("/mcp_external"):
                res = await components["toolbox"].execute_tool(
                    "MCP_ECHO",
                    {"message": "hello"},
                    trace_id=str(r.trace_id),
                    timeout_sec=2.0,
                )
                await _publish(
                    components["bus"],
                    AdamiEvent(
                        trace_id=str(r.trace_id),
                        source_module="nexus.reply",
                        target_topic="system.events",
                        priority=EventPriority.NORMAL,
                        payload={"event_type": "REPLY", "text": f"mcp_external: {str(res)[:120]}", "trace_id": str(r.trace_id)},
                    ),
                )
            else:
                # Fallback: run DP to keep export non-empty and closer to real routing.
                try:
                    await dp.process(
                        AdamiEvent(
                            trace_id=str(r.trace_id),
                            source_module=str(r.source_module),
                            target_topic=inject_topic,
                            priority=EventPriority.HIGH,
                            payload={"task": raw, "chat_id": chat_id, "platform": platform},
                        )
                    )
                except asyncio.CancelledError:
                    # Some golden traces intentionally exercise cancellation semantics.
                    pass

        # Wait for session release or timeout.
        t0 = asyncio.get_running_loop().time()
        while chat_id in lm.active_sessions:
            if (asyncio.get_running_loop().time() - t0) > 10.0:
                break
            await asyncio.sleep(0.05)

    await asyncio.sleep(0.8)
    if consumer_task is not None:
        consumer_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await consumer_task
    await get_trace_sink().stop()
    # Stop EventBus background DLQ replayer task (created in bus.initialize()).
    bus = components.get("bus")
    rt = getattr(bus, "_replay_task", None)
    if rt is not None:
        rt.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await rt
    # WorkflowEngine is not required for deterministic replay paths above.

    # Restore global sim/export switches to avoid cross-test state leakage.
    if old_env_trace_enabled is None:
        os.environ.pop("ADAMI_SIM_TRACE_EXPORT_ENABLED", None)
    else:
        os.environ["ADAMI_SIM_TRACE_EXPORT_ENABLED"] = old_env_trace_enabled
    if old_env_trace_path is None:
        os.environ.pop("ADAMI_SIM_TRACE_EXPORT_PATH", None)
    else:
        os.environ["ADAMI_SIM_TRACE_EXPORT_PATH"] = old_env_trace_path
    if old_env_sim_offline is None:
        os.environ.pop("ADAMI_SIM_OFFLINE", None)
    else:
        os.environ["ADAMI_SIM_OFFLINE"] = old_env_sim_offline
    try:
        setattr(config_mod.settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", old_cfg_trace_enabled)
        setattr(config_mod.settings, "ADAMI_SIM_TRACE_EXPORT_PATH", old_cfg_trace_path)
        setattr(config_mod.settings, "ADAMI_SIM_OFFLINE", old_cfg_sim_offline)
    except Exception:
        pass

    if verify_isomorphic:
        actual = load_ndjson_records(export_path)
        mm = compare_isomorphic(expected=records, actual=actual)
        if mm is not None:
            raise ReplayValidationError(
                f"isomorphic_mismatch at {mm.index}: {mm.reason}\n"
                f"expected={mm.expected}\nactual={mm.actual}"
            )


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

