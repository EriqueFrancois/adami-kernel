"""Step 4: intake archive body reuses MultiModalInput when file_path is present."""

from __future__ import annotations

from pathlib import Path

import pytest

from adami_kernel.cortex.decision_processor import _intake_archive_body_from_payload


class _MM:
    def __init__(self, res: dict) -> None:
        self._res = res
        self.last: tuple[str, dict] | None = None

    async def process_input(self, media_type: str, payload: dict) -> dict:
        self.last = (media_type, dict(payload))
        return self._res


class _TB:
    def __init__(self, mm: _MM) -> None:
        self.multi_modal = mm


class _K:
    def __init__(self, mm: _MM | None) -> None:
        self.toolbox = _TB(mm) if mm is not None else None


@pytest.mark.asyncio
async def test_intake_without_file_path_returns_task() -> None:
    body, src = await _intake_archive_body_from_payload("note body", {}, _K(_MM({})))
    assert body == "note body"
    assert src == ""


@pytest.mark.asyncio
async def test_intake_missing_file_returns_task(tmp_path: Path) -> None:
    mm = _MM({"type": "raw_multi_modal", "raw_content": "x", "media_type": "file", "task": "t"})
    body, src = await _intake_archive_body_from_payload(
        "t", {"file_path": str(tmp_path / "missing.pdf")}, _K(mm)
    )
    assert body == "t"
    assert src == ""
    assert mm.last is None


@pytest.mark.asyncio
async def test_intake_text_result_keeps_task(tmp_path: Path) -> None:
    p = tmp_path / "a.pdf"
    p.write_bytes(b"%PDF-1.4")
    mm = _MM({"type": "text", "content": "no parser", "task": ""})
    body, src = await _intake_archive_body_from_payload(
        "user caption", {"file_path": str(p), "file_name": "a.pdf"}, _K(mm)
    )
    assert body == "user caption"
    assert src == ""


@pytest.mark.asyncio
async def test_intake_raw_multi_modal_prefers_markdown(tmp_path: Path) -> None:
    p = tmp_path / "b.pdf"
    p.write_bytes(b"%PDF-1.4")
    mm = _MM(
        {"type": "raw_multi_modal", "raw_content": "# H1\n", "media_type": "file", "task": "t"}
    )
    body, src = await _intake_archive_body_from_payload(
        "/intake", {"file_path": str(p), "file_name": "b.pdf"}, _K(mm)
    )
    assert body == "# H1\n"
    assert src == "b.pdf"
    assert mm.last == ("document", {"file_path": str(p), "file_name": "b.pdf"})


@pytest.mark.asyncio
async def test_intake_prepends_note_after_intake_prefix(tmp_path: Path) -> None:
    p = tmp_path / "c.pdf"
    p.write_bytes(b"%PDF-1.4")
    mm = _MM({"type": "raw_multi_modal", "raw_content": "MD", "media_type": "file", "task": "t"})
    body, src = await _intake_archive_body_from_payload(
        "/intake\nmy note line", {"file_path": str(p), "file_name": "c.pdf"}, _K(mm)
    )
    assert "my note line" in body
    assert "MD" in body
    assert src == "c.pdf"
