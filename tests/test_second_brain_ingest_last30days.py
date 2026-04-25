from __future__ import annotations

from pathlib import Path

from adami_kernel.hippocampus.second_brain import SecondBrainManager


def test_write_inbox_note_is_under_root_and_retrievable(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    sb = SecondBrainManager(str(root))

    p = sb.write_inbox_note(
        "last30days Daily Digest",
        "This is a digest about PARA and last30days.\n",
        tags=["last30days", "digest"],
        source="last30days",
        dedupe_key="daily:last30days",
        filename_prefix="last30days",
    )

    assert p.is_file()
    assert str(p.resolve()).startswith(str(root.resolve()))
    assert "Inbox" in p.parts

    text = p.read_text(encoding="utf-8")
    assert "# last30days Daily Digest" in text
    assert "This is a digest" in text

    # retrieve should see either summary or title hits (title contains last30days)
    out = sb.retrieve_brain_snippets("last30days", max_files=5)
    assert out
    assert "Inbox/" in out


def test_write_resource_note_goes_to_resources(tmp_path: Path) -> None:
    root = tmp_path / "brain"
    sb = SecondBrainManager(str(root))

    p = sb.write_resource_note(
        "Rust async notes",
        "Resource body.\n",
        tags=["rust"],
        source="unit-test",
        filename_prefix="resource",
    )

    assert p.is_file()
    assert "Resources" in p.parts
