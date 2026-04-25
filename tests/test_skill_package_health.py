"""
Skill 包体检：确保 ``src/adami_kernel/skill_manager/`` 下全部 .py 可导入，
并对核心无 I/O 路径做轻量冒烟（不启 Docker / Chroma）。
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

import adami_kernel.skill_manager as skill_manager_pkg
from adami_kernel.skill_manager.skill_lifecycle import SkillLifecycle, SkillStatus
from adami_kernel.skill_manager.skill_validation_result import ValidationResult
from adami_kernel.skill_manager.skill_validator import SkillValidator


def _skill_manager_py_modules() -> list[str]:
    root = Path(skill_manager_pkg.__file__).resolve().parent
    names: list[str] = []
    for p in sorted(root.glob("*.py")):
        names.append(f"adami_kernel.skill_manager.{p.stem}")
    return names


@pytest.mark.parametrize("module_name", _skill_manager_py_modules())
def test_skill_manager_submodule_imports(module_name: str) -> None:
    """27 个文件 ↔ 27 个子模块（含包内 ``skill_manager`` 自身通过 ``__init__`` 已加载）。"""
    mod = importlib.import_module(module_name)
    assert mod is not None


def test_skill_manager_package_count_matches_disk() -> None:
    root = Path(skill_manager_pkg.__file__).resolve().parent
    py_files = [p for p in root.glob("*.py") if p.is_file()]
    assert len(py_files) == 27, f"expected 27 .py files under skill_manager, found {len(py_files)}"


def test_skill_validator_static_minimal_skill_passes() -> None:
    code = """
import asyncio

async def execute(**kwargs):
    return {"status": "success", "result": {}}
"""
    r = SkillValidator.validate_static(code, "TEST_SKILL_HEALTH")
    assert r.passed, r.errors


def test_skill_validator_static_syntax_fail() -> None:
    r = SkillValidator.validate_static("not python {{{", "BAD")
    assert not r.passed
    assert any(e.get("type") == "syntax" for e in r.errors)


def test_skill_lifecycle_transitions() -> None:
    lc = SkillLifecycle(skill_name="X")
    lc.transition_to(SkillStatus.CREATED, "ok")
    assert lc.current_status == SkillStatus.CREATED


def test_validation_result_add_error() -> None:
    vr = ValidationResult(passed=True)
    vr.add_error("t", "m", suggestion="s")
    assert not vr.passed
    assert vr.errors and vr.errors[0]["type"] == "t"


def test_skill_manager_public_exports() -> None:
    """``__init__.py`` 导出的符号均可从包根导入。"""
    for name in getattr(skill_manager_pkg, "__all__", []):
        assert hasattr(skill_manager_pkg, name), f"missing __all__ export: {name}"


def test_skill_manager_no_nested_source_dirs() -> None:
    """当前设计为单层 ``*.py``，不应出现除 ``__pycache__`` 外的子源码目录。"""
    root = Path(skill_manager_pkg.__file__).resolve().parent
    bad_dirs = [c.name for c in root.iterdir() if c.is_dir() and c.name not in ("__pycache__",)]
    assert not bad_dirs, f"unexpected directories under skill_manager: {bad_dirs}"
