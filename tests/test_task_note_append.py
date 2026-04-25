"""步骤 16：TASK_NOTE 写入 tasks.md「## 待办」段。"""

from __future__ import annotations

from adami_kernel.cortex.intent_router import extract_task_note_body
from adami_kernel.cortex.tasks_md_utils import append_checkbox_under_todo_section
from adami_kernel.i18n.boot_msg import boot_t


def test_append_checkbox_adds_one_line_under_todo():
    todo_h = boot_t("cjk_gate.tasks_md_heading_todo")
    template = "# 任务池\n" "## 焦点（最重要的 1-3 件）\n" f"{todo_h}\n" "## 已完成\n"
    before_n = len(template.splitlines())
    out = append_checkbox_under_todo_section(template, "明天开会", "2026-04-09")
    lines = out.splitlines()
    assert len(lines) == before_n + 1
    assert "- [ ] 明天开会 | 📅 2026-04-09" in lines
    idx = lines.index(todo_h)
    assert lines[idx + 1] == "- [ ] 明天开会 | 📅 2026-04-09"
    assert lines[idx + 2] == "## 已完成"


def test_extract_task_note_body_chinese_and_slash():
    assert extract_task_note_body("帮我记一下 递交周报") == "递交周报"
    assert extract_task_note_body("/task 致电法务") == "致电法务"


def test_task_note_writes_file_one_extra_line(tmp_path):
    todo_h = boot_t("cjk_gate.tasks_md_heading_todo")
    tasks = tmp_path / "System" / "working-memory" / "tasks.md"
    tasks.parent.mkdir(parents=True, exist_ok=True)
    base = "# 任务池\n" "## 焦点（最重要的 1-3 件）\n" f"{todo_h}\n" "## 已完成\n"
    tasks.write_text(base, encoding="utf-8")
    n0 = len(tasks.read_text(encoding="utf-8").splitlines())
    body = extract_task_note_body("帮我记一下 单元测试一条")
    out = append_checkbox_under_todo_section(tasks.read_text(encoding="utf-8"), body, "2099-01-01")
    tasks.write_text(out, encoding="utf-8")
    n1 = len(tasks.read_text(encoding="utf-8").splitlines())
    assert n1 == n0 + 1
