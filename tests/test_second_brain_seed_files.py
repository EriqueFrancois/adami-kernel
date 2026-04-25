"""SecondBrain.initialize 播种文件验收（仅依赖 second_brain，避免拉全 Cortex 链）。"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from adami_kernel.hippocampus.second_brain import SecondBrainManager


def test_initialize_seeds_tasks_and_pending_approvals():
    d = Path(tempfile.mkdtemp(prefix="t6_sbinit_"))
    sb = SecondBrainManager(str(d))
    asyncio.run(sb.initialize())
    tasks = d / "System" / "working-memory" / "tasks.md"
    pending = d / "System" / "pending_approvals.md"
    assert tasks.is_file()
    assert pending.is_file()
    t = tasks.read_text(encoding="utf-8")
    p = pending.read_text(encoding="utf-8")
    assert "# 任务池" in t
    assert "## 焦点（最重要的 1-3 件）" in t
    assert "## 待办" in t
    assert "## 已完成" in t
    assert "# 审批队列" in p
    assert "## 待审批" in p
