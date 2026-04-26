"""集成：SkillFactory（模板后端）→ SkillBuilder → EvolutionEngine.create_new_skill 全链路。"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

import adami_kernel.config as config


pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_create_new_skill_template_weather_pipeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """
    使用 ``ADAMI_SKILL_BACKEND=template`` + 天气描述命中内置模板，避免 GitHub/LLM/ Docker。
    ``ADAMI_DATA_DIR`` 与 ``EvolutionEngine.base_dir`` 对齐，保证 ``SkillBuilder`` 写入路径与
    ``SkillFileLoader`` 加载路径一致。
    """
    monkeypatch.setattr(config.settings, "ADAMI_DATA_DIR", str(tmp_path), raising=False)
    monkeypatch.setattr(config.settings, "ADAMI_SKILL_BACKEND", "template", raising=False)
    monkeypatch.setattr(
        config.settings, "ADAMI_SKILL_VALIDATOR_SANDBOX_ENABLED", False, raising=False
    )

    from adami_kernel.cortex.evolution import EvolutionEngine
    from adami_kernel.hippocampus.layered_memory import LayeredMemory
    from adami_kernel.skill_manager.skill_template_repository import SkillTemplateRepository

    SkillTemplateRepository.clear_template_cache()

    memory = LayeredMemory()
    ee = EvolutionEngine(toolbox=None, memory=memory, base_dir=str(tmp_path), dream_sandbox=None)

    skill_name = "WEATHER_E2E_SKILL"
    description = "query weather for city Beijing using wttr"

    out = await ee.create_new_skill(skill_name=skill_name, description=description)

    assert out.get("status") == "success", out
    data = out.get("data") or {}
    skill_path = data.get("skill_path")
    assert skill_path and os.path.isfile(skill_path)
    assert skill_path.endswith(f"{skill_name}.py")

    # ``get_skill`` 返回的是 ``SkillUsageManager`` 包装后的 **协程函数**，不是带 ``execute`` 的模块。
    fn = ee.get_skill(skill_name)
    assert fn is not None
    assert asyncio.iscoroutinefunction(fn)
