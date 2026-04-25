"""SkillManager：Anthropic 相关内存缓存键与 ``inspect_and_register`` 一致（大写）。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from adami_kernel.skill_manager.skill_manager import SkillManager
from adami_kernel.skill_manager.skill_metadata import SkillMetadata, SkillVersion


@pytest.mark.asyncio
async def test_get_skill_metadata_hits_anthropic_cache_with_mixed_case() -> None:
    memory = MagicMock()
    memory.retrieve_recent = AsyncMock(return_value=[])
    evolution = MagicMock()
    dream_sandbox = MagicMock()
    router = MagicMock()

    sm = SkillManager(memory, evolution, dream_sandbox, router, vector_store=None)
    meta = SkillMetadata.model_construct(
        skill_name="ANTHROPIC_DEMO",
        current_version="1.0",
        prompt_template="body",
        versions={
            "1.0": SkillVersion(version="1.0", code="", score=100.0, reason="test"),
        },
        status="active",
    )
    sm._anthropic_cache["ANTHROPIC_DEMO"] = meta

    assert await sm.get_skill_metadata("anthropic_demo") is meta
    assert await sm.get_skill_metadata("Anthropic_Demo") is meta
