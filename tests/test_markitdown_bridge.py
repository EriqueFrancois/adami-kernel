"""
Step 7: MarkItDown bridge (Steps 2–3) — regression matrix for kernel ↔ multimodal.

Matrix (see docs/document_parsing_baseline_step0.md Step 7):
- Mock MarkItDown failure → unstructured ``partition`` path (fake ``unstructured`` in ``sys.modules``; no pip install).
- At least one whitelisted extension with real MarkItDown when optional extra is installed (``pytest.importorskip("markitdown")``).

PR / CI: default ``poetry install`` job may skip real-convert rows; job ``markitdown-bridge`` runs
``poetry install -E markitdown`` + this file only.
"""

from __future__ import annotations

import sys
import types
import zipfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from adami_kernel.cortex import document_markdown as dm
from adami_kernel.cortex.multi_modal import MultiModalInput

pytestmark = [pytest.mark.markitdown_bridge]


def _write_minimal_docx(path: Path) -> None:
    """Tiny valid .docx (OOXML) for MarkItDown without optional pptx/pdf stack."""
    document_xml = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:body>
    <w:p><w:r><w:t>BRIDGE_STEP7_DOCX_TOKEN</w:t></w:r></w:p>
  </w:body>
</w:document>"""
    content_types = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    word_rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("[Content_Types].xml", content_types)
        zf.writestr("_rels/.rels", rels)
        zf.writestr("word/document.xml", document_xml)
        zf.writestr("word/_rels/document.xml.rels", word_rels)


@pytest.fixture
def fake_unstructured_modules(monkeypatch: pytest.MonkeyPatch) -> str:
    """Minimal ``unstructured`` package so ``MultiModalInput`` enables partition without pip."""
    if "unstructured.partition.auto" in sys.modules:
        mod = sys.modules["unstructured.partition.auto"]
        if not getattr(mod, "_adami_test_fake_partition", False):
            pytest.skip("real unstructured.partition.auto already loaded; isolate this file")

    marker = "FAKE_UNSTRUCTURED_BRIDGE"

    def _partition(**_kwargs: object) -> list[object]:
        class _El:
            def __str__(self) -> str:
                return marker

        return [_El()]

    root = types.ModuleType("unstructured")
    part = types.ModuleType("unstructured.partition")
    auto = types.ModuleType("unstructured.partition.auto")
    auto.partition = _partition
    auto._adami_test_fake_partition = True  # noqa: SLF001 — test-only sentinel on a stub module

    keys = [
        "unstructured",
        "unstructured.partition",
        "unstructured.partition.auto",
    ]
    for name, mod in zip(
        keys,
        (root, part, auto),
        strict=True,
    ):
        monkeypatch.setitem(sys.modules, name, mod)

    return marker


@pytest.fixture
def mm_fake_u(fake_unstructured_modules: str) -> MultiModalInput:
    return MultiModalInput(MagicMock(), MagicMock())


@pytest.mark.asyncio
async def test_bridge_fallback_markitdown_conversion_failed_uses_partition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mm_fake_u: MultiModalInput,
    fake_unstructured_modules: str,
) -> None:
    monkeypatch.setattr(
        "adami_kernel.cortex.multi_modal.markitdown_effective_enabled", lambda: True
    )
    p = tmp_path / "fail.pdf"
    p.write_bytes(b"%PDF-1.4")

    async def _fail_convert(*_a, **_k):
        return dm.DocumentMarkdownFailure(
            reason=dm.DocumentMarkdownFailureReason.CONVERSION_FAILED,
            detail="mock",
        )

    monkeypatch.setattr(dm, "convert_document_path_to_markdown", _fail_convert)
    mm_fake_u.unstructured_available = True
    out = await mm_fake_u._process_file({"file_path": str(p), "file_name": "fail.pdf"})
    assert out["type"] == "raw_multi_modal"
    assert fake_unstructured_modules in out["raw_content"]


@pytest.mark.asyncio
async def test_bridge_fallback_markitdown_timeout_uses_partition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mm_fake_u: MultiModalInput,
    fake_unstructured_modules: str,
) -> None:
    monkeypatch.setattr(
        "adami_kernel.cortex.multi_modal.markitdown_effective_enabled", lambda: True
    )
    p = tmp_path / "to.pdf"
    p.write_bytes(b"%PDF-1.4")

    async def _timeout_convert(*_a, **_k):
        return dm.DocumentMarkdownFailure(reason=dm.DocumentMarkdownFailureReason.TIMEOUT)

    monkeypatch.setattr(dm, "convert_document_path_to_markdown", _timeout_convert)
    mm_fake_u.unstructured_available = True
    out = await mm_fake_u._process_file({"file_path": str(p), "file_name": "to.pdf"})
    assert out["type"] == "raw_multi_modal"
    assert fake_unstructured_modules in out["raw_content"]


@pytest.mark.asyncio
async def test_bridge_fallback_file_too_large_uses_partition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mm_fake_u: MultiModalInput,
    fake_unstructured_modules: str,
) -> None:
    monkeypatch.setattr(
        "adami_kernel.cortex.multi_modal.markitdown_effective_enabled", lambda: True
    )
    p = tmp_path / "big.pdf"
    p.write_bytes(b"%PDF-1.4")

    async def _too_large(*_a, **_k):
        return dm.DocumentMarkdownFailure(
            reason=dm.DocumentMarkdownFailureReason.FILE_TOO_LARGE,
            detail="mock",
        )

    monkeypatch.setattr(dm, "convert_document_path_to_markdown", _too_large)
    mm_fake_u.unstructured_available = True
    out = await mm_fake_u._process_file({"file_path": str(p), "file_name": "big.pdf"})
    assert out["type"] == "raw_multi_modal"
    assert fake_unstructured_modules in out["raw_content"]


@pytest.mark.asyncio
async def test_bridge_real_docx_markitdown_roundtrip(tmp_path: Path) -> None:
    """One real whitelisted extension (docx) when ``poetry install -E markitdown`` is present."""
    pytest.importorskip("markitdown", reason="poetry install -E markitdown")
    docx = tmp_path / "bridge.docx"
    _write_minimal_docx(docx)
    res = await dm.convert_document_path_to_markdown(docx)
    assert isinstance(res, dm.DocumentMarkdownSuccess), res
    assert "BRIDGE_STEP7_DOCX_TOKEN" in res.markdown.replace("\\_", "_")


@pytest.mark.parametrize(
    "name,expected",
    [
        ("x.pdf", ".pdf"),
        ("a.DOCX", ".docx"),
        ("slides.PpTx", ".pptx"),
        ("book.xlsx", ".xlsx"),
    ],
)
def test_bridge_whitelist_four_suffixes(name: str, expected: str) -> None:
    assert dm.normalized_allowed_extension(name) == expected
