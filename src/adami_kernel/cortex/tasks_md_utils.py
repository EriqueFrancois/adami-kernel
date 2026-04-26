# src/adami_kernel/cortex/tasks_md_utils.py
"""tasks.md 纯函数工具（无 router 依赖，可供测试与 DecisionProcessor 复用）。"""

from __future__ import annotations

from typing import Optional

from adami_kernel.i18n.boot_msg import boot_t


def append_checkbox_under_todo_section(content: str, body: str, date_s: str) -> str:
    """在「## 待办」段末尾插入一行 `- [ ] … | 📅 …`；无该标题则在文末补段。"""
    todo_heading = boot_t("cjk_gate.tasks_md_heading_todo")
    line = f"- [ ] {body} | 📅 {date_s}"
    lines = content.split("\n")
    idx: Optional[int] = None
    for i, ln in enumerate(lines):
        if ln.strip() == todo_heading:
            idx = i
            break
    if idx is None:
        tail = content.rstrip()
        sep = "\n\n" if tail else ""
        return f"{tail}{sep}{todo_heading}\n{line}\n"
    j = idx + 1
    while j < len(lines) and not lines[j].startswith("## "):
        j += 1
    lines.insert(j, line)
    joined = "\n".join(lines)
    if not joined.endswith("\n"):
        joined += "\n"
    return joined
