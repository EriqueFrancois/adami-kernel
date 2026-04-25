"""Step 6: document parse ops — MarkItDown toggle, timeouts, max bytes, AdamI-DocumentParse routes."""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path

import pytest

from adami_kernel.config import markitdown_effective_enabled, settings
from adami_kernel.cortex import document_markdown as dm
from adami_kernel.cortex.multi_modal import MultiModalInput


@pytest.fixture
def mm() -> MultiModalInput:
    from unittest.mock import MagicMock

    return MultiModalInput(MagicMock(), MagicMock())


def test_markitdown_effective_enabled_false_and_true(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ADAMI_MARKITDOWN_ENABLED", False)
    assert markitdown_effective_enabled() is False
    monkeypatch.setattr(settings, "ADAMI_MARKITDOWN_ENABLED", True)
    assert markitdown_effective_enabled() is True


def test_markitdown_effective_enabled_auto_uses_find_spec(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ADAMI_MARKITDOWN_ENABLED", None)
    orig = importlib.util.find_spec

    def _fake(name: str):
        if name == "markitdown":
            return None
        return orig(name)

    monkeypatch.setattr(importlib.util, "find_spec", _fake)
    assert markitdown_effective_enabled() is False


@pytest.mark.asyncio
async def test_convert_path_file_too_large(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    p = tmp_path / "x.pdf"
    p.write_bytes(b"%PDF-1.4\nextra")
    monkeypatch.setattr(dm, "markitdown_import_spec", lambda: object())
    monkeypatch.setattr(settings, "ADAMI_DOCUMENT_MARKDOWN_MAX_INPUT_BYTES", 5)
    result = await dm.convert_document_path_to_markdown(p)
    assert isinstance(result, dm.DocumentMarkdownFailure)
    assert result.reason == dm.DocumentMarkdownFailureReason.FILE_TOO_LARGE


@pytest.mark.asyncio
async def test_multi_modal_markitdown_disabled_skips_converter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mm: MultiModalInput,
    caplog: pytest.LogCaptureFixture,
) -> None:
    pytest.importorskip("unstructured")
    monkeypatch.setattr(settings, "ADAMI_MARKITDOWN_ENABLED", False)
    p = tmp_path / "d.pdf"
    p.write_bytes(b"%PDF-1.4")

    called: list[int] = []

    async def _boom(*_a, **_k):
        called.append(1)
        raise AssertionError("convert should not run when MarkItDown disabled")

    monkeypatch.setattr(dm, "convert_document_path_to_markdown", _boom)

    def _fake_partition(**_kwargs):
        class _El:
            def __str__(self) -> str:
                return "STEP6_DISABLED_OK"

        return [_El()]

    monkeypatch.setattr("unstructured.partition.auto.partition", _fake_partition)
    mm.unstructured_available = True
    caplog.set_level(logging.INFO)
    out = await mm._process_file({"file_path": str(p), "file_name": "d.pdf"})
    assert not called
    assert "STEP6_DISABLED_OK" in out["raw_content"]
    assert any("route=markitdown_skipped" in r.message for r in caplog.records)
    assert any("reason=config_false" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_multi_modal_unstructured_ok_logs_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mm: MultiModalInput,
    caplog: pytest.LogCaptureFixture,
) -> None:
    pytest.importorskip("unstructured")
    monkeypatch.setattr(
        "adami_kernel.cortex.multi_modal.markitdown_effective_enabled", lambda: True
    )
    p = tmp_path / "e.pdf"
    p.write_bytes(b"%PDF-1.4")

    async def _no_md(*_a, **_k):
        return dm.DocumentMarkdownFailure(
            reason=dm.DocumentMarkdownFailureReason.NOT_INSTALLED,
            detail=None,
        )

    monkeypatch.setattr(dm, "convert_document_path_to_markdown", _no_md)

    def _fake_partition(**_kwargs):
        class _El:
            def __str__(self) -> str:
                return "U_OK"

        return [_El()]

    monkeypatch.setattr("unstructured.partition.auto.partition", _fake_partition)
    mm.unstructured_available = True
    caplog.set_level(logging.INFO)
    await mm._process_file({"file_path": str(p), "file_name": "e.pdf"})
    assert any("route=unstructured_ok" in r.message for r in caplog.records)
    assert any("prior_markitdown=failed" in r.message for r in caplog.records)
