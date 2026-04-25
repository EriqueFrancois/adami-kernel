"""IM-port plain formatting for Report Studio chat pushes."""

from __future__ import annotations

from adami_kernel.peripheral.report_studio.report_port_format import (
    plain_report_text_for_im_channels,
)


def test_plain_strips_headings_hr_list_bold_links() -> None:
    md = """# Title

> meta line

## 1) Section
### 1. First item
Body line

---

### 2. **Bold title** ([source](https://example.com/a))
- **USD:** $100
* bullet text
"""
    out = plain_report_text_for_im_channels(md)
    assert "#" not in out
    assert "##" not in out
    assert "###" not in out
    assert "---" not in out
    assert "**" not in out
    assert "Title" in out
    assert "meta line" in out
    assert "1) Section" in out
    assert "1. First item" in out
    assert "Body line" in out
    assert "Bold title" in out
    assert "source (https://example.com/a)" in out
    assert "USD: $100" in out
    assert "bullet text" in out


def test_plain_empty_input() -> None:
    assert plain_report_text_for_im_channels("") == ""
    assert plain_report_text_for_im_channels("   \n\n  ") == ""
