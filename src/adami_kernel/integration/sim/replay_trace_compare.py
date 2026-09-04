"""Trace-level comparison for isomorphic replay validation.

This is stricter than suite score comparisons: it checks whether a replayed trace
emits an event stream that is *structurally* identical to the golden trace after
normalization (timestamps, ids, and other volatile fields are ignored).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Sequence

from adami_kernel.integration.sim.schema import ReplayTraceRecordV1


@dataclass(frozen=True)
class TraceMismatch:
    index: int
    reason: str
    expected: Dict[str, Any]
    actual: Dict[str, Any]


def _stable_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    p = dict(payload or {})
    # drop volatile fields
    for k in ("trace_id", "episode_id", "latency_ms", "retry_count"):
        if k in p:
            p.pop(k, None)
    et = p.get("event_type")
    # Normalize known volatile paths in golden traces.
    if et == "REPORT_DONE" and isinstance(p.get("note_path"), str):
        p["note_path"] = ".adami_data/brain/Inbox/report-daily.md"
    if et == "INTAKE_DONE" and isinstance(p.get("note_path"), str):
        p["note_path"] = ".adami_data/brain/Inbox/intake-note.md"
    if et == "PHASE_TRANSITION":
        # checkpoint_seq can vary across workflow implementations; keep semantic route only.
        p.pop("checkpoint_seq", None)
    if et == "REPLY" and isinstance(p.get("text"), str):
        txt = str(p["text"])
        # Align with capture normalization for deterministic golden traces.
        if "Report 已生成并写入" in txt:  # adami:allow-cjk replay normalization for zh report reply
            txt = "✅ Report generated"
        if "Saved to SecondBrain" in txt:
            txt = "✅ Saved to SecondBrain"
        # Queue UX messages include positions/counts that depend on persisted queue state.
        # Normalize them so isomorphic replay doesn't fail due to non-semantic numbering.
        if "已加入队列" in txt or "joined the queue" in txt.lower():  # adami:allow-cjk replay normalization for zh queue replies
            txt = "🧠 queued"
        if "已清空队列" in txt or "queue discarded" in txt.lower():  # adami:allow-cjk replay normalization for zh queue replies
            txt = "✅ queue_discarded"
        if "queue status" in txt.lower() or "队列状态" in txt:  # adami:allow-cjk replay normalization for zh queue replies
            txt = "✅ queue_status"
        if "no running task to cancel" in txt.lower() or "可取消" in txt:  # adami:allow-cjk replay normalization for zh queue replies
            txt = "ℹ️ queue_cancel"
        if "cancellation requested" in txt.lower() or "已请求取消" in txt:  # adami:allow-cjk replay normalization for zh queue replies
            txt = "✅ queue_cancel_requested"
        if "task cancelled" in txt.lower() or "已取消当前任务" in txt:  # adami:allow-cjk replay normalization for zh queue replies
            txt = "⚠️ queue_cancelled"
        if "queue continued" in txt.lower() or "post-cancel" in txt.lower() or "队列已继续处理" in txt:  # adami:allow-cjk replay normalization for zh queue replies
            txt = "✅ queue_continued"
        p["text"] = txt[:240]
    if isinstance(et, str) and et.startswith("TOOL_CALL_"):
        # For tool lifecycle events, compare the semantic core only.
        keep: Dict[str, Any] = {}
        for k in ("event_type", "tool", "timeout_sec"):
            if k in p:
                keep[k] = p.get(k)
        p = keep
        # keep shape but avoid huge payload diffs
        # (We intentionally ignore `result` here; it can include volatile fields and is already gated by eval scorecards.)
    return p


def _stable_record(r: ReplayTraceRecordV1) -> Dict[str, Any]:
    payload = _stable_payload(dict(r.payload_redacted or {}))
    et = payload.get("event_type")
    src = str(r.source_module)
    # Source modules may legitimately differ across implementations (e.g. router emit site),
    # but tool lifecycle semantics must remain stable. Normalize those here.
    if isinstance(et, str) and et.startswith("TOOL_CALL_"):
        src = "(toolcall)"
    return {
        "target_topic": str(r.target_topic),
        "source_module": src,
        "payload": payload,
    }


def compare_isomorphic(
    *,
    expected: Sequence[ReplayTraceRecordV1],
    actual: Sequence[ReplayTraceRecordV1],
) -> Optional[TraceMismatch]:
    exp = [_stable_record(r) for r in expected]
    act = [_stable_record(r) for r in actual]
    if len(exp) != len(act):
        return TraceMismatch(
            index=min(len(exp), len(act)),
            reason=f"length_mismatch: expected={len(exp)} actual={len(act)}",
            expected={"length": len(exp)},
            actual={"length": len(act)},
        )
    for i, (e, a) in enumerate(zip(exp, act, strict=True)):
        if e != a:
            return TraceMismatch(index=i, reason="record_mismatch", expected=e, actual=a)
    return None

