"""Step 3: MultiModalInput document path — MarkItDown-first, unstructured fallback."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock

import pytest

from adami_kernel.cortex import document_markdown as dm
from adami_kernel.cortex.multi_modal import MultiModalInput


@pytest.fixture
def mm() -> MultiModalInput:
    return MultiModalInput(MagicMock(), MagicMock())


@pytest.mark.asyncio
async def test_whitelist_markdown_success_without_unstructured(
    tmp_path, monkeypatch: pytest.MonkeyPatch, mm: MultiModalInput
) -> None:
    monkeypatch.setattr(
        "adami_kernel.cortex.multi_modal.markitdown_effective_enabled", lambda: True
    )
    p = tmp_path / "a.pdf"
    p.write_bytes(b"%PDF-1.4")

    async def _fake_convert(*_a, **_k):
        return dm.DocumentMarkdownSuccess(
            markdown="# Doc\nbody",
            meta=dm.DocumentMarkdownMeta(truncated=False, original_char_length=10, title=None),
        )

    monkeypatch.setattr(dm, "convert_document_path_to_markdown", _fake_convert)
    mm.unstructured_available = False
    out = await mm._process_file({"file_path": str(p), "file_name": "a.pdf"})
    assert out["type"] == "raw_multi_modal"
    assert out["raw_content"].startswith("# Doc")
    assert out["media_type"] == "file"


@pytest.mark.asyncio
async def test_markitdown_not_installed_falls_back_to_unstructured(
    tmp_path, monkeypatch: pytest.MonkeyPatch, mm: MultiModalInput
) -> None:
    pytest.importorskip("unstructured")
    p = tmp_path / "b.pdf"
    p.write_bytes(b"%PDF-1.4")

    async def _fake_convert(*_a, **_k):
        return dm.DocumentMarkdownFailure(
            reason=dm.DocumentMarkdownFailureReason.NOT_INSTALLED,
            detail=None,
        )

    monkeypatch.setattr(dm, "convert_document_path_to_markdown", _fake_convert)

    def _fake_partition(**_kwargs):
        class _El:
            def __str__(self) -> str:
                return "FROM_UNSTRUCTURED"

        return [_El()]

    monkeypatch.setattr(
        "unstructured.partition.auto.partition",
        _fake_partition,
    )
    mm.unstructured_available = True
    out = await mm._process_file({"file_path": str(p), "file_name": "b.pdf"})
    assert out["type"] == "raw_multi_modal"
    assert "FROM_UNSTRUCTURED" in out["raw_content"]


@pytest.mark.asyncio
async def test_non_whitelist_does_not_call_markdown_converter(
    tmp_path, monkeypatch: pytest.MonkeyPatch, mm: MultiModalInput
) -> None:
    pytest.importorskip("unstructured")
    p = tmp_path / "note.txt"
    p.write_text("plain", encoding="utf-8")

    async def _boom(*_a, **_k):
        raise AssertionError("convert_document_path_to_markdown should not run for .txt")

    monkeypatch.setattr(dm, "convert_document_path_to_markdown", _boom)

    def _fake_partition(**_kwargs):
        class _El:
            def __str__(self) -> str:
                return "TXT_OK"

        return [_El()]

    monkeypatch.setattr("unstructured.partition.auto.partition", _fake_partition)
    mm.unstructured_available = True
    out = await mm._process_file({"file_path": str(p), "file_name": "note.txt"})
    assert "TXT_OK" in out["raw_content"]


@pytest.mark.asyncio
async def test_neither_markitdown_nor_unstructured_returns_i18n_message(
    tmp_path, monkeypatch: pytest.MonkeyPatch, mm: MultiModalInput
) -> None:
    p = tmp_path / "c.pdf"
    p.write_bytes(b"%PDF-1.4")

    async def _fake_convert(*_a, **_k):
        return dm.DocumentMarkdownFailure(
            reason=dm.DocumentMarkdownFailureReason.NOT_INSTALLED,
            detail=None,
        )

    monkeypatch.setattr(dm, "convert_document_path_to_markdown", _fake_convert)
    mm.unstructured_available = False
    out = await mm._process_file({"file_path": str(p), "file_name": "c.pdf"})
    assert out["type"] == "text"
    assert "markitdown" in out["content"].lower()


@pytest.mark.asyncio
async def test_markitdown_not_installed_logs_info_not_error(
    tmp_path, monkeypatch: pytest.MonkeyPatch, mm: MultiModalInput, caplog: pytest.LogCaptureFixture
) -> None:
    pytest.importorskip("unstructured")
    p = tmp_path / "d.pdf"
    p.write_bytes(b"%PDF-1.4")

    async def _fake_convert(*_a, **_k):
        return dm.DocumentMarkdownFailure(
            reason=dm.DocumentMarkdownFailureReason.NOT_INSTALLED,
            detail=None,
        )

    monkeypatch.setattr(dm, "convert_document_path_to_markdown", _fake_convert)

    def _fake_partition(**_kwargs):
        class _El:
            def __str__(self) -> str:
                return "OK"

        return [_El()]

    monkeypatch.setattr("unstructured.partition.auto.partition", _fake_partition)
    mm.unstructured_available = True
    caplog.set_level(logging.INFO)
    await mm._process_file({"file_path": str(p), "file_name": "d.pdf"})
    assert not any(r.levelno >= logging.ERROR for r in caplog.records)
    assert any("[MultiModal]" in r.getMessage() for r in caplog.records)
