"""
Module 6 (i18n) — Steps 0–1 acceptance.

Step 0: boundary policy doc exists; README links it; doc contains A/B/C + BCP47 anchors.
Step 1: packaged JSON catalogs + Translator fallback/override + safe interpolation behavior.
"""

from pathlib import Path

import pytest

from adami_kernel.i18n.catalog import Translator, normalize_locale
from adami_kernel.i18n.keys import UI


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def test_step0_i18n_boundary_doc_exists_and_linked_from_readme() -> None:
    root = _repo_root()
    frag = "docs/i18n_boundary_and_locale_policy.md"
    doc = root / frag
    assert doc.is_file(), "Step 0 i18n boundary doc should exist"
    readme = (root / "README.md").read_text(encoding="utf-8")
    assert frag in readme, "README should link the i18n boundary doc"


@pytest.mark.parametrize(
    "keyword",
    [
        "A —",
        "B —",
        "C —",
        "BCP 47",
        "`en`",
        "`zh-Hans`",
    ],
)
def test_step0_i18n_boundary_doc_contains_review_keywords(keyword: str) -> None:
    doc = _repo_root() / "docs" / "i18n_boundary_and_locale_policy.md"
    text = doc.read_text(encoding="utf-8")
    assert keyword in text, f"boundary doc should contain {keyword!r}"


def test_step1_default_catalogs_load_and_fallback() -> None:
    assert normalize_locale("zh_CN") == "zh-Hans"
    tr = Translator(default_locale="zh-Hans")
    s = tr.t(UI.MENU_ENTRY)
    assert s.startswith("1")

    tr2 = Translator(default_locale="en")
    assert tr2.t(UI.MENU_ENTRY).startswith("1")


def test_step1_missing_placeholder_is_readable_error() -> None:
    tr = Translator(default_locale="en")
    try:
        tr.t("errors.report.json_invalid")
    except ValueError as e:
        msg = str(e)
        assert "missing placeholder" in msg
        assert "detail" in msg
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")
