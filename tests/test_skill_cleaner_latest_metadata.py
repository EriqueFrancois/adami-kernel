"""SkillCleaner：同一 skill 多条元数据时必须采用 LayeredMemory 中的最新一条。"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from adami_kernel.skill_manager.skill_cleaner import SkillCleaner


@pytest.mark.asyncio
async def test_load_metadata_keeps_latest_row_per_skill(tmp_path: Path) -> None:
    """retrieve_recent 返回旧→新；后出现的记录应覆盖同名技能。"""
    memory = MagicMock()
    memory.retrieve_recent = AsyncMock(
        return_value=[
            {"skill_name": "DEMO_SKILL", "status": "active", "metrics": {"total_calls": 0}},
            {
                "skill_name": "DEMO_SKILL",
                "status": "deleted",
                "metrics": {"total_calls": 99},
            },
        ]
    )
    evolution = MagicMock()
    evolution.skills_dir = str(tmp_path / "skills")
    evolution.instincts_dir = str(tmp_path / "instincts")

    cleaner = SkillCleaner(memory, evolution, vector_store=None, skill_version_manager=None)
    rows = await cleaner._load_metadata()
    assert len(rows) == 1
    assert rows[0]["status"] == "deleted"
    assert rows[0]["metrics"]["total_calls"] == 99
