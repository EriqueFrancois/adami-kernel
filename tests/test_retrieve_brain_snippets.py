"""步骤 17：retrieve_brain_snippets 主动检索（README + summary 规则级）。"""

from __future__ import annotations

from pathlib import Path

from adami_kernel.hippocampus.second_brain import (
    SecondBrainManager,
    _parse_md_summary_and_first_heading,
)


def test_parse_md_summary_and_first_heading():
    md = (
        "---\n"
        "para: inbox\n"
        "summary: 'PARA 与 第二大脑'\n"
        "---\n\n"
        "# 我的笔记标题\n\n"
        "正文。\n"
    )
    s, t = _parse_md_summary_and_first_heading(md)
    assert "PARA" in s
    assert "第二大脑" in s
    assert t == "我的笔记标题"


def test_retrieve_brain_snippets_returns_nonempty_when_summary_matches(tmp_path: Path):
    root = tmp_path / "brain"
    (root / "Inbox").mkdir(parents=True)
    note = root / "Inbox" / "note_para.md"
    note.write_text(
        "---\n" "summary: AdamI 内核 与 PARA 工作流\n" "---\n\n" "# 无关标题\n",
        encoding="utf-8",
    )
    sb = SecondBrainManager(str(root))
    out = sb.retrieve_brain_snippets("PARA", max_files=3)
    assert out
    assert "Inbox/note_para.md" in out
    assert "AdamI" in out or "PARA" in out


def test_retrieve_brain_snippets_matches_title_without_frontmatter(tmp_path: Path):
    root = tmp_path / "brain"
    (root / "Resources").mkdir(parents=True)
    note = root / "Resources" / "rust_async.md"
    note.write_text("# Rust 异步编程备忘\n\n正文\n", encoding="utf-8")
    sb = SecondBrainManager(str(root))
    out = sb.retrieve_brain_snippets("Rust 异步", max_files=2)
    assert out
    assert "Resources/rust_async.md" in out


def test_retrieve_brain_snippets_skips_report_studio_notes(tmp_path: Path):
    root = tmp_path / "brain"
    inbox = root / "Inbox"
    inbox.mkdir(parents=True)
    (inbox / "report-2026-04-11-report-daily.md").write_text(
        "---\n"
        "title: report: daily (2026-04-11)\n"
        "summary: '# 日报简报'\n"
        "source: report_studio\n"
        "---\n\n"
        "# 日报简报\n",
        encoding="utf-8",
    )
    (inbox / "note_para.md").write_text(
        "---\nsummary: PARA 工作流与日报无关笔记\n---\n\n# PARA\n",
        encoding="utf-8",
    )
    sb = SecondBrainManager(str(root))
    out = sb.retrieve_brain_snippets("日报 PARA", max_files=5)
    assert "report-2026-04-11" not in out
    assert "Inbox/note_para.md" in out


def test_retrieve_brain_snippets_prefers_filename_date_recency(tmp_path: Path):
    root = tmp_path / "brain"
    inbox = root / "Inbox"
    inbox.mkdir(parents=True)
    (inbox / "note_20260404_old.md").write_text(
        "---\nsummary: 全球重大新闻摘录\n---\n\n# 旧闻\n",
        encoding="utf-8",
    )
    (inbox / "note_20260903_new.md").write_text(
        "---\nsummary: 全球重大新闻摘录\n---\n\n# 新讯\n",
        encoding="utf-8",
    )
    sb = SecondBrainManager(str(root))
    out = sb.retrieve_brain_snippets("全球重大新闻", max_files=1)
    assert "note_20260903_new.md" in out
    assert "note_20260404_old.md" not in out
