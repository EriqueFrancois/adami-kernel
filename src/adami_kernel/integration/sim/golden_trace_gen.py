"""Golden trace generator using real kernel export transform.

This generates deterministic golden traces by:
- building real ``AdamiEvent`` objects (the kernel event envelope)
- converting them via ``integration.sim.trace_sink.event_to_record`` (same path as EventBus export)
- normalizing timestamps to stable values for CI

It intentionally does **not** boot the whole kernel; the goal is to keep traces
small, deterministic, and focused on contract-level fields (topic/payload/phase).
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from adami_kernel.integration.sim.schema import ReplayTraceRecordV1
from adami_kernel.integration.sim.trace_sink import event_to_record
from adami_kernel.nexus.event import AdamiEvent, EventPriority
from adami_kernel.telemetry.experience_sink import experience_episode_id_ctx


@dataclass(frozen=True)
class TraceScenario:
    name: str
    episode_id: str
    base_ts: float


def _normalize_ts(records: Sequence[ReplayTraceRecordV1], *, base_ts: float, step: float = 0.5) -> list[ReplayTraceRecordV1]:
    out: list[ReplayTraceRecordV1] = []
    t = float(base_ts)
    for r in records:
        out.append(r.model_copy(update={"ts": t}))
        t += float(step)
    return out


def _write_ndjson(path: Path, records: Sequence[ReplayTraceRecordV1]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "".join([r.to_ndjson_line() for r in records])
    path.write_text(text, encoding="utf-8")


def _ev(*, trace_id: str, source_module: str, target_topic: str = "system.events", payload: dict) -> AdamiEvent:
    return AdamiEvent(
        trace_id=trace_id,
        source_module=source_module,
        target_topic=target_topic,
        priority=EventPriority.NORMAL,
        payload=payload,
    )


def _records_from_events(*, episode_id: str, events: Iterable[AdamiEvent]) -> list[ReplayTraceRecordV1]:
    token = experience_episode_id_ctx.set(episode_id)
    try:
        return [event_to_record(e) for e in events]
    finally:
        experience_episode_id_ctx.reset(token)


def build_report_daily() -> list[ReplayTraceRecordV1]:
    events = [
        _ev(
            trace_id="rep-1",
            source_module="user.prompt",
            payload={"task": "/report run daily", "platform": "cli", "chat_id": "cli"},
        ),
        _ev(
            trace_id="rep-1",
            source_module="peripheral.report_studio",
            payload={"event_type": "PHASE_TRANSITION", "to_phase": "REPORT_START", "checkpoint_seq": 1},
        ),
        _ev(
            trace_id="rep-1",
            source_module="peripheral.report_studio",
            payload={
                "event_type": "REPORT_DONE",
                "rtype": "daily",
                "note_path": ".adami_data/brain/Inbox/report-daily.md",
            },
        ),
        _ev(
            trace_id="rep-1",
            source_module="nexus.reply",
            payload={"text": "✅ Report generated", "trace_id": "rep-1"},
        ),
    ]
    recs = _records_from_events(episode_id="ep-report", events=events)
    return _normalize_ts(recs, base_ts=2000.0)


def build_intake() -> list[ReplayTraceRecordV1]:
    events = [
        _ev(
            trace_id="int-1",
            source_module="user.prompt",
            payload={"task": "/intake Remember: AdamI stores notes in SecondBrain.", "platform": "cli", "chat_id": "cli"},
        ),
        _ev(
            trace_id="int-1",
            source_module="orchestrator.intake",
            payload={"event_type": "PHASE_TRANSITION", "to_phase": "INTAKE_START", "checkpoint_seq": 1},
        ),
        _ev(
            trace_id="int-1",
            source_module="hippocampus.second_brain",
            payload={"event_type": "INTAKE_DONE", "note_path": ".adami_data/brain/Inbox/intake-note.md", "tags": ["intake"]},
        ),
        _ev(
            trace_id="int-1",
            source_module="nexus.reply",
            payload={"text": "✅ Saved to SecondBrain", "trace_id": "int-1"},
        ),
    ]
    recs = _records_from_events(episode_id="ep-intake", events=events)
    return _normalize_ts(recs, base_ts=3000.0)


def build_tool_timeout() -> list[ReplayTraceRecordV1]:
    events = [
        _ev(
            trace_id="tool-1",
            source_module="user.prompt",
            payload={"task": "Run tool: slow_operation()", "platform": "cli", "chat_id": "cli"},
        ),
        _ev(
            trace_id="tool-1",
            source_module="mcp.client",
            payload={"event_type": "TOOL_CALL_START", "tool": "slow_operation", "timeout_sec": 2.0},
        ),
        _ev(
            trace_id="tool-1",
            source_module="mcp.client",
            payload={"event_type": "TOOL_CALL_TIMEOUT", "tool": "slow_operation", "timeout_sec": 2.0},
        ),
        _ev(
            trace_id="tool-1",
            source_module="nexus.reply",
            payload={"text": "Tool timed out. Please try again or reduce scope.", "trace_id": "tool-1"},
        ),
    ]
    recs = _records_from_events(episode_id="ep-tool", events=events)
    return _normalize_ts(recs, base_ts=4000.0)


def generate_all(*, out_dir: Path) -> None:
    suites = {
        "report_daily": build_report_daily(),
        "intake": build_intake(),
        "tool_timeout": build_tool_timeout(),
    }
    for name, recs in suites.items():
        _write_ndjson(out_dir / name / "golden_trace.ndjson", recs)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Generate golden traces (deterministic, export-compatible).")
    p.add_argument(
        "--out-dir",
        type=Path,
        default=Path("docs/evals/traces"),
        help="Target directory to write suites into (default: docs/evals/traces)",
    )
    args = p.parse_args(argv)
    generate_all(out_dir=args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

