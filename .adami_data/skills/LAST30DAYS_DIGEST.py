from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from adami_kernel.config import settings
from adami_kernel.hippocampus.second_brain import write_inbox_note, write_resource_note
from adami_kernel.integration.last30days_bridge import run_last30days


def _pick_note_writer(write_to: str):
    return write_resource_note if str(write_to).strip().lower() == "resources" else write_inbox_note


def _stringify_result(payload: Dict[str, Any]) -> str:
    for key in ("context", "markdown", "text"):
        val = payload.get(key)
        if isinstance(val, str) and val.strip():
            return val
    data = payload.get("data")
    if isinstance(data, str) and data.strip():
        return data
    return str(payload.get("raw") or "")


async def execute(
    *,
    topic: str,
    emit: str = "context",
    write_to: str = "Inbox",
    refresh: bool = False,
    sources: str = "auto",
) -> Dict[str, Any]:
    if not bool(getattr(settings, "ADAMI_LAST30DAYS_ENABLED", False)):
        return {"ok": False, "error": "module5 disabled"}

    bridge_out = await run_last30days(
        topic=topic,
        emit=emit,
        sources=sources,
        refresh=bool(refresh),
    )
    if not bool(bridge_out.get("ok")):
        return {"ok": False, "error": str(bridge_out.get("error") or "last30days failed")}

    body = _stringify_result(bridge_out).strip()
    if not body:
        body = "(empty digest)"

    writer = _pick_note_writer(write_to)
    prefix = str(getattr(settings, "ADAMI_LAST30DAYS_NOTE_PREFIX", "last30days")).strip() or "last30days"
    filename = f"{prefix}_digest.md"
    note_path = writer(filename=filename, content=body)

    return {
        "ok": True,
        "note_path": str(Path(note_path)),
        "write_to": str(write_to),
        "topic": str(topic),
        "emit": str(emit),
    }
