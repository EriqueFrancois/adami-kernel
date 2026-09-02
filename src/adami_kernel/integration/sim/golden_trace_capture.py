"""Capture golden traces by running a minimal in-process kernel path.

This boots:
- ComponentInitializer (for core components)
- EventBus.initialize() (so middleware + trace sink are active)
- LifecycleManager._event_consumer() (DecisionProcessor processing)

Then it publishes CLI-like events to `system.events`, waits briefly, and writes
the exported NDJSON to the target trace path with normalized timestamps.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import os
import time
from pathlib import Path
from typing import List, Sequence

import adami_kernel.config as config_mod
from adami_kernel.core.component_initializer import ComponentInitializer
from adami_kernel.core.lifecycle_manager import LifecycleManager
from adami_kernel.integration.sim.replay import load_ndjson_records, validate_phase1_records
from adami_kernel.integration.sim.schema import ReplayTraceRecordV1
from adami_kernel.integration.sim.trace_sink import get_trace_sink
from adami_kernel.nexus.event import AdamiEvent, EventPriority


def _normalize_ts(records: Sequence[ReplayTraceRecordV1], *, base_ts: float, step: float = 0.5) -> list[ReplayTraceRecordV1]:
    out: list[ReplayTraceRecordV1] = []
    t = float(base_ts)
    for r in records:
        out.append(r.model_copy(update={"ts": t}))
        t += float(step)
    return out


def _write_ndjson(path: Path, records: Sequence[ReplayTraceRecordV1]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join([r.to_ndjson_line() for r in records]), encoding="utf-8")


def _normalize_payload(records: Sequence[ReplayTraceRecordV1]) -> list[ReplayTraceRecordV1]:
    """Scrub machine-specific paths from golden traces."""
    out: list[ReplayTraceRecordV1] = []
    for r in records:
        payload = dict(r.payload_redacted or {})
        et = payload.get("event_type")
        if et == "REPORT_DONE" and isinstance(payload.get("note_path"), str):
            payload["note_path"] = ".adami_data/brain/Inbox/report-daily.md"
        if et == "INTAKE_DONE" and isinstance(payload.get("note_path"), str):
            payload["note_path"] = ".adami_data/brain/Inbox/intake-note.md"
        if et == "REPLY" and isinstance(payload.get("text"), str):
            txt = payload["text"]
            txt = txt.replace(str(payload.get("note_path") or ""), str(payload.get("note_path") or ""))
            # best-effort: collapse absolute paths into stable placeholders
            txt = txt.replace("`/Users/", "`/.adami_data/") if "`/Users/" in txt else txt
            if "Report 已生成并写入" in txt:  # adami:allow-cjk replay normalization for zh report reply
                payload["text"] = "✅ Report generated"
            elif "Saved to SecondBrain" in txt:
                payload["text"] = "✅ Saved to SecondBrain"
            else:
                payload["text"] = txt[:240]
        out.append(r.model_copy(update={"payload_redacted": payload}))
    return out


async def _capture_once(*, tasks: List[str]) -> None:
    # minimal boot: components + bus middleware + consumer loop
    components = ComponentInitializer().initialize_components(kernel=None)
    lm = LifecycleManager(components)

    want_second_brain = any(
        (str(x or "").strip().lower().startswith("/report") or str(x or "").strip().lower().startswith("/intake"))
        for x in tasks
    )
    # Ensure critical components are ready (only when needed).
    if want_second_brain and components.get("second_brain") is not None:
        await components["second_brain"].initialize()
    await components["bus"].initialize()
    try:
        # publish tasks as CLI events
        chat_id = "cli"
        from adami_kernel.cortex.decision_processor_report_actions import run_report_action

        from adami_kernel.cortex.decision_processor import DecisionProcessor

        # Workflow engine should be running for workflow traces.
        await components["workflow_engine"].initialize()

        dp = DecisionProcessor(lm)
        for i, t in enumerate(tasks, start=1):
            lm.active_sessions[chat_id] = {"trace_id": f"golden_cmd_{i:03d}"}
            # Keep captures deterministic: clear any persisted queue state for this chat.
            try:
                tq0 = getattr(lm, "task_queue", None)
                if tq0 is not None:
                    tq0.discard_all(chat_id)
            except Exception:
                pass
            ev = AdamiEvent(
                trace_id=f"golden_cmd_{i:03d}",
                source_module="user.prompt",
                target_topic="system.events",
                priority=EventPriority.HIGH,
                payload={"task": t, "chat_id": chat_id, "platform": "cli"},
            )
            await components["bus"].publish(ev)

            raw = (t or "").strip()
            if raw.lower().startswith("/report"):
                await run_report_action(dp, raw, chat_id, "cli")
            elif raw.lower().startswith("/intake"):
                await dp._handle_intake_action(raw, chat_id, "cli", payload={})  # type: ignore[attr-defined]
            elif raw.lower().startswith("/tool_timeout"):
                # Use the real kernel tool execution path (DecisionProcessor action -> ToolboxManager).
                await dp._execute_action(  # type: ignore[attr-defined]
                    "EXECUTE_COMMAND",
                    {"command": "sleep 2", "timeout_sec": 0.2},
                    chat_id,
                    "cli",
                    trace_id=f"golden_cmd_{i:03d}",
                    task_text="/tool_timeout",
                )
            elif raw.lower().startswith("/workflow_engine"):
                from adami_kernel.orchestrator.workflow_models import Node, WorkflowState

                wfe = components["workflow_engine"]
                # Capture should not depend on local sqlite state; use an in-memory workflow store.
                class _Mem:
                    def __init__(self) -> None:
                        self._states: dict[tuple[str, str], WorkflowState] = {}

                    async def save_workflow_state(self, state: WorkflowState) -> None:
                        self._states[(str(state.chat_id), str(state.workflow_id))] = state

                    async def get_workflow_state(self, workflow_id: str, chat_id: str):
                        return self._states.get((str(chat_id), str(workflow_id)))

                    async def save_workflow_phase_checkpoint(self, *args, **kwargs):
                        class _Res:
                            ok = False
                            seq = 0

                        return _Res()

                wfe.memory = _Mem()  # type: ignore[assignment]

                wid = "wf_golden_001"
                # Emit a "planner submitted workflow" marker into system.events for trace readability.
                await components["bus"].publish(
                    AdamiEvent(
                        trace_id=f"golden_cmd_{i:03d}",
                        source_module="orchestrator.planner",
                        target_topic="system.events",
                        priority=EventPriority.NORMAL,
                        payload={"event_type": "WORKFLOW_SUBMIT", "workflow_id": wid, "chat_id": chat_id},
                    )
                )

                state = WorkflowState(
                    workflow_id=wid,
                    chat_id=chat_id,
                    status="PENDING",
                    current_node_id="__start__",
                    nodes={
                        "__start__": Node(node_id="__start__", node_type="START", timeout=5),
                        "tool_echo": Node(
                            node_id="tool_echo",
                            node_type="TOOL",
                            timeout=5,
                            config={
                                "command": "echo workflow_ok",
                                # Avoid isolated sandbox run (keeps capture fast/deterministic).
                                "long_task_disable_isolated_run": True,
                            },
                        ),
                        "__end__": Node(node_id="__end__", node_type="END", timeout=5),
                    },
                    edges={"__start__": ["tool_echo"], "tool_echo": ["__end__"], "__end__": []},
                    context={"original_task": "workflow_engine_smoke"},
                )

                fut = await wfe.run_composed_state(state)
                await asyncio.wait_for(fut, timeout=8.0)

                # User-visible completion marker (lifecycle contract evidence: include workflow_id).
                await components["bus"].publish(
                    AdamiEvent(
                        trace_id=f"golden_cmd_{i:03d}",
                        source_module="nexus.reply",
                        target_topic="system.events",
                        priority=EventPriority.NORMAL,
                        payload={
                            "event_type": "REPLY",
                            "text": f"✅ Workflow completed (workflow_id={wid})",
                            "trace_id": f"golden_cmd_{i:03d}",
                        },
                    )
                )
            elif raw.lower().startswith("/llm_call"):
                # Deterministic offline LLM call (router emits TOOL_CALL_* lifecycle).
                text = await components["router"].call_llm(
                    "hello_llm",
                    brain_type="think",
                    timeout_sec=2.0,
                )
                await components["bus"].publish(
                    AdamiEvent(
                        trace_id=f"golden_cmd_{i:03d}",
                        source_module="nexus.reply",
                        target_topic="system.events",
                        priority=EventPriority.NORMAL,
                        payload={
                            "event_type": "REPLY",
                            "text": text[:240],
                            "trace_id": f"golden_cmd_{i:03d}",
                        },
                    )
                )
            elif raw.lower().startswith("/web_search"):
                rows = await components["toolbox"].web_search(
                    "adami kernel",
                    max_results=3,
                    trace_id=f"golden_cmd_{i:03d}",
                    timeout_sec=2.0,
                )
                await components["bus"].publish(
                    AdamiEvent(
                        trace_id=f"golden_cmd_{i:03d}",
                        source_module="nexus.reply",
                        target_topic="system.events",
                        priority=EventPriority.NORMAL,
                        payload={
                            "event_type": "REPLY",
                            "text": f"web_search results: {len(rows)}",
                            "trace_id": f"golden_cmd_{i:03d}",
                        },
                    )
                )
            elif raw.lower().startswith("/mcp_external"):
                # Deterministic external tool path (simulates MCP executor).
                async def _ext_echo(message: str = "") -> dict:
                    return {"message": str(message)}

                components["toolbox"].register_external_tools(
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
                res = await components["toolbox"].execute_tool(
                    "MCP_ECHO",
                    {"message": "hello"},
                    trace_id=f"golden_cmd_{i:03d}",
                    timeout_sec=2.0,
                )
                await components["bus"].publish(
                    AdamiEvent(
                        trace_id=f"golden_cmd_{i:03d}",
                        source_module="nexus.reply",
                        target_topic="system.events",
                        priority=EventPriority.NORMAL,
                        payload={
                            "event_type": "REPLY",
                            "text": f"mcp_external: {str(res)[:120]}",
                            "trace_id": f"golden_cmd_{i:03d}",
                        },
                    )
                )
            elif raw.lower().startswith("/toolchoice"):
                # Full DP-driven scenario (offline deterministic) to cover multi-turn LLM + tool choice.
                await dp.process(ev)
            else:
                # Fallback: run through DP so the trace reflects normal routing.
                try:
                    await dp.process(ev)
                except asyncio.CancelledError:
                    # Some golden traces intentionally exercise cancellation semantics.
                    pass

            # Wait for CLI session to be released to avoid leaving dangling locks.
            t0 = time.monotonic()
            while True:
                if chat_id not in lm.active_sessions:
                    tq_wait = getattr(lm, "task_queue", None)
                    try:
                        if tq_wait is None or not tq_wait.has_pending_or_in_progress(chat_id):
                            break
                    except Exception:
                        break
                if (time.monotonic() - t0) > 8.0:
                    break
                await asyncio.sleep(0.05)

        # allow sink flush
        await asyncio.sleep(2.0)
    finally:
        with contextlib.suppress(Exception):
            await get_trace_sink().stop()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Capture golden trace by running minimal kernel path.")
    p.add_argument("--task", action="append", default=[], help="Task text to publish (repeatable)")
    p.add_argument("--out-trace", type=Path, required=True, help="Output golden_trace.ndjson path")
    p.add_argument("--base-ts", type=float, default=2000.0, help="Normalized base timestamp")
    p.add_argument("--export-path", type=Path, default=None, help="Temp export path (defaults under /tmp)")
    args = p.parse_args(argv)

    tasks: List[str] = [str(x) for x in (args.task or []) if str(x).strip()]
    if not tasks:
        raise SystemExit("no --task provided")

    export_path = args.export_path or (Path("/tmp") / "adami_eventbus_export.ndjson")
    try:
        export_path.unlink()
    except FileNotFoundError:
        pass

    # Turn on export + offline mode via env, then reload settings.
    os.environ["ADAMI_SIM_TRACE_EXPORT_ENABLED"] = "1"
    os.environ["ADAMI_SIM_TRACE_EXPORT_PATH"] = str(export_path)
    os.environ["ADAMI_SIM_OFFLINE"] = "1"
    os.environ["ADAMI_REPORT_TRANSLATE_NEWS"] = "0"
    os.environ["ADAMI_REPORT_CRYPTO_ENABLED"] = "0"
    # NOTE: many modules import `settings` by value (`from adami_kernel.config import settings`),
    # so `reload_settings()` would not update their references. For capture we mutate the existing
    # settings object in-place so the whole process sees consistent flags.
    try:
        setattr(config_mod.settings, "ADAMI_SIM_TRACE_EXPORT_ENABLED", True)
        setattr(config_mod.settings, "ADAMI_SIM_TRACE_EXPORT_PATH", str(export_path))
        setattr(config_mod.settings, "ADAMI_SIM_OFFLINE", True)
        setattr(config_mod.settings, "ADAMI_REPORT_TRANSLATE_NEWS", False)
        setattr(config_mod.settings, "ADAMI_REPORT_CRYPTO_ENABLED", False)
    except Exception:
        pass

    asyncio.run(_capture_once(tasks=tasks))

    records = load_ndjson_records(export_path)
    validate_phase1_records(records, allow_empty=False, monotonic_ts=False)
    normalized = _normalize_ts(_normalize_payload(records), base_ts=float(args.base_ts))
    _write_ndjson(args.out_trace, normalized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

