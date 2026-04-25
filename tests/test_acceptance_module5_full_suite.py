# -*- coding: utf-8 -*-
"""模块五（last30days 外部 CLI 世界传感器）— 整体验收说明与轻量门禁

验收方案（与 ``docs/module5_last30days_integration.md`` 对齐）
============================================================

1. **边界与默认行为**：不将 last30days 作为默认 Python 依赖；``ADAMI_LAST30DAYS_ENABLED``
   默认关闭；桥接层仅子进程 + 解析 stdout + 安全落盘 SecondBrain。

2. **桥接层契约**：``run_last30days`` 在脚本存在时可解析 emit；脚本缺失 / 超时 /
   错误路径返回结构化结果；TTL 缓存与可选限流 / ddgs 降级行为由
   ``tests/test_last30days_bridge.py`` 覆盖。

3. **SecondBrain 落盘**：ingest 路径生成预期 frontmatter / 去重键 / 检索可见性
   （``tests/test_second_brain_ingest_last30days.py``）。

4. **原生技能**：``LAST30DAYS_DIGEST`` 技能执行链写 Inbox/Resources（
   ``tests/test_skill_last30days_digest.py``，依赖仓库内 ``.adami_data/skills`` 样例）。

5. **昼夜节律调度**：开关 + topic 满足时发布 ``system.events``；每日 / 每周
   trace 前缀与冷却退避（``tests/test_acceptance_module5_last30days_daily_digest.py``）。

6. **Planner 消化闭环**：LAST30DAYS 成功后调度 digest 任务并落 StageArtifact（
   ``tests/test_acceptance_module5_last30days_digest_loop.py``）。

7. **回归**：与 Report Studio 等共用 fake CLI 的用例互不冲突；本文件仅做
   **轻量 import / 配置键 / SecondBrainManager 写笔记方法** 烟测。``TaskPlanner`` 消化闭环由
   ``test_acceptance_module5_last30days_digest_loop.py`` 覆盖（不在此顶层 import ``planner``，
   避免经 ``meta_cortex`` 拉 mlx 等重依赖）。

一键执行（模块五专项，不跑全仓）::

  poetry run pytest \\
    tests/test_acceptance_module5_full_suite.py \\
    tests/test_last30days_bridge.py \\
    tests/test_second_brain_ingest_last30days.py \\
    tests/test_skill_last30days_digest.py \\
    tests/test_acceptance_module5_last30days_daily_digest.py \\
    tests/test_acceptance_module5_last30days_digest_loop.py \\
    -v --tb=short

全仓门禁仍建议：``pytest -m \"not integration\"``。
"""

from __future__ import annotations

from pathlib import Path

import pytest

from adami_kernel.config import settings
from adami_kernel.hippocampus import second_brain as second_brain_mod
from adami_kernel.integration import last30days_bridge as bridge_mod
from adami_kernel.peripheral import circadian_nerve as circadian_mod


def test_module5_bridge_module_importable() -> None:
    assert hasattr(bridge_mod, "run_last30days")


def test_module5_second_brain_write_apis_present() -> None:
    sb_cls = getattr(second_brain_mod, "SecondBrainManager", None)
    assert sb_cls is not None
    assert hasattr(sb_cls, "write_inbox_note")
    assert hasattr(sb_cls, "write_resource_note")


def test_module5_circadian_nerve_importable() -> None:
    """昼夜节律入口（勿在此文件顶层 import planner，避免经 meta_cortex 拉 mlx）。"""
    assert hasattr(circadian_mod, "CircadianNerve")


def test_module5_settings_keys_exist() -> None:
    """配置项在 Settings 上可访问（默认值由 pydantic 提供）。"""
    for name in (
        "ADAMI_LAST30DAYS_ENABLED",
        "ADAMI_LAST30DAYS_SCRIPT_PATH",
        "ADAMI_LAST30DAYS_EMIT_MODE",
        "ADAMI_LAST30DAYS_TIMEOUT_SEC",
        "ADAMI_LAST30DAYS_DAILY_TOPIC",
        "ADAMI_LAST30DAYS_WEEKLY_TOPIC",
        "ADAMI_LAST30DAYS_WRITE_TO",
        "ADAMI_LAST30DAYS_NOTE_PREFIX",
        "ADAMI_LAST30DAYS_TRANSLATE_DIGEST",
        "ADAMI_LAST30DAYS_DIGEST_SOURCE_LOCALE",
    ):
        assert hasattr(settings, name), f"missing settings.{name}"


@pytest.fixture()
def last30days_skill_path() -> Path:
    return Path(__file__).resolve().parents[1] / ".adami_data" / "skills" / "LAST30DAYS_DIGEST.py"


def test_module5_digest_skill_file_present(last30days_skill_path: Path) -> None:
    """仓库内随附的技能样例存在（技能单测依赖）。"""
    assert last30days_skill_path.is_file(), (
        f"expected bundled skill at {last30days_skill_path} "
        "(see docs/module5_last30days_integration.md)"
    )
