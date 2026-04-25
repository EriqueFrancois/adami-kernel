"""小条（5）/步骤 13：candidates.md 重复观察规范化去重后标 🔴。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from adami_kernel.hippocampus.consolidation import SemanticConsolidator, _normalize_candidate_body


def test_normalize_candidate_body_collapses_whitespace_and_lower():
    assert _normalize_candidate_body("  User  prefers  SHORT ") == "user prefers short"


def test_mark_duplicate_candidates_first_green_rest_red(tmp_path: Path):
    cand = tmp_path / "candidates.md"
    cand.write_text(
        "# 偏好候选池\n"
        "## 待确认\n"
        "- 🟢 [2026-01-01] 观察：喜欢 分点列表\n"
        "- 🟢 [2026-01-02] 观察：喜欢   分点列表\n"
        "- 🟢 [2026-01-03] 观察：另一件事\n",
        encoding="utf-8",
    )
    con = SemanticConsolidator(MagicMock(), MagicMock())
    con._mark_duplicate_candidates_red(str(cand))
    lines = [ln for ln in cand.read_text(encoding="utf-8").splitlines() if "观察：" in ln]
    assert lines[0].startswith("- 🟢")
    assert lines[1].startswith("- 🔴")
    assert lines[2].startswith("- 🟢")


def test_mark_duplicate_noop_when_single_candidate(tmp_path: Path):
    cand = tmp_path / "candidates.md"
    original = "- 🟢 [2026-01-01] 观察：唯一一条\n"
    cand.write_text("# x\n" + original, encoding="utf-8")
    con = SemanticConsolidator(MagicMock(), MagicMock())
    con._mark_duplicate_candidates_red(str(cand))
    assert cand.read_text(encoding="utf-8") == "# x\n" + original
