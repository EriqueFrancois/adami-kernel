"""Step 1: MarkItDown is an optional Poetry extra (not part of default install)."""

from __future__ import annotations

import tomllib
from pathlib import Path


def test_pyproject_markitdown_optional_and_extra_group() -> None:
    raw = Path(__file__).resolve().parents[1] / "pyproject.toml"
    data = tomllib.loads(raw.read_text(encoding="utf-8"))
    poetry = data["tool"]["poetry"]
    deps = poetry["dependencies"]
    md = deps["markitdown"]
    assert isinstance(md, dict)
    assert md.get("optional") is True
    assert md.get("version") == "~0.1.5"
    extras = md.get("extras") or []
    for name in ("pdf", "docx", "pptx", "xlsx"):
        assert name in extras
    groups = poetry["extras"]
    assert "markitdown" in groups
    assert groups["markitdown"] == ["markitdown"]
