"""验收：步骤 0（依赖/extras）与步骤 1（对齐文档）。

验收方案（自动项在本文件；需人工或 CI job 的项在 docstring 末）
----------------------------------------------------------------
**步骤 0**
- AC-0.1 ``pyproject.toml``：存在 optional ``mcp-agent``，版本 pin 为 ``0.2.6``。
- AC-0.2 ``[tool.poetry.extras]``：extra 键名为 ``mcp-agent``，且列出依赖 ``mcp-agent``。
- AC-0.3 ``poetry.lock``：可解析到 mcp-agent 0.2.6（与 pin 一致）。
- AC-0.4 **未装 extra 时**：AdamI 配置与 ``planner_bridge`` 模块可导入，且不 **强制** 依赖已安装 ``mcp_agent`` 包
  （``mcp_agent`` 仅在被调用路径中 lazy import）。
- AC-0.5 **已装 extra 时**（当前 venv 若已 ``poetry install -E mcp-agent``）：``import mcp_agent`` 成功且 ``__version__`` 或
  metadata 与 0.2.6 一致（见 ``test_when_mcp_agent_installed_version_matches_pin``）。

**步骤 1**
- AC-1.1 存在 ``docs/mcp_agent_alignment.md``。
- AC-1.2 文档含 §0 依赖/冲突说明与 §1 概念映射表。
- AC-1.3 评审维度覆盖：LLM、MCP session、tool schema、执行与审计（关键词检测）。

**建议人工 / CI 流水线**（本文件不强制执行）
- ``poetry install``（无 ``-E``）后 ``pip list | grep -i mcp-agent`` 无包；``poetry install -E mcp-agent`` 后有包。
- ``pip install -e ".[mcp-agent]"`` 在干净 venv 可成功（与 Poetry 元数据一致）。
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
LOCK = ROOT / "poetry.lock"
ALIGNMENT = ROOT / "docs" / "mcp_agent_alignment.md"


def _poetry_toml() -> dict:
    try:
        import tomllib
    except ImportError:
        import tomli as tomllib  # type: ignore[no-redef,import-not-found]

    with PYPROJECT.open("rb") as f:
        return tomllib.load(f)


def test_ac_0_1_optional_mcp_agent_pinned() -> None:
    data = _poetry_toml()
    deps = data["tool"]["poetry"]["dependencies"]
    mcp = deps.get("mcp-agent")
    assert isinstance(mcp, dict), "mcp-agent 应为 dict（optional + version）"
    assert mcp.get("optional") is True
    assert mcp.get("version") == "0.2.6"


def test_ac_0_2_extra_mcp_agent_named_and_wired() -> None:
    data = _poetry_toml()
    extras = data["tool"]["poetry"]["extras"]
    assert "mcp-agent" in extras
    assert extras["mcp-agent"] == ["mcp-agent"]


def test_ac_0_3_lockfile_contains_mcp_agent_release() -> None:
    text = LOCK.read_text(encoding="utf-8")
    assert 'name = "mcp-agent"' in text
    assert "0.2.6" in text


def test_ac_0_4_adami_loads_without_hard_mcp_agent_dependency() -> None:
    """导入 bridge 不得触发 mcp_agent 顶级导入；用独立进程避免同会话内其它测试先 import adapter 造成误报。"""
    src = str(ROOT / "src")
    prev = os.environ.get("PYTHONPATH", "")
    env = {
        **os.environ,
        "PYTHONPATH": f"{src}{os.pathsep}{prev}" if prev else src,
    }
    code = (
        "import sys\n"
        "import adami_kernel.integration.mcp_agent.planner_bridge as bridge\n"
        "from adami_kernel.config import settings\n"
        "assert bridge is not None\n"
        "assert settings is not None\n"
        "assert 'mcp_agent' not in sys.modules\n"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert proc.returncode == 0, f"stderr={proc.stderr!r} stdout={proc.stdout!r}"


def test_ac_1_1_alignment_doc_exists() -> None:
    assert ALIGNMENT.is_file()


def test_ac_1_2_alignment_doc_sections() -> None:
    body = ALIGNMENT.read_text(encoding="utf-8")
    assert "## 0." in body or "§0" in body
    assert "## 1." in body or "概念映射" in body
    assert "冲突" in body or "numpy" in body


def test_ac_1_3_alignment_covers_review_dimensions() -> None:
    body = ALIGNMENT.read_text(encoding="utf-8")
    lowered = body.lower()
    assert "llm" in lowered or "hybridllmrouter" in lowered
    assert "session" in lowered or "连接" in body or "mcpconnectionmanager" in lowered
    assert "schema" in lowered or "工具" in body
    assert "审计" in body or "experience_sink" in body or "执行" in body


def test_when_mcp_agent_installed_version_matches_pin() -> None:
    """仅当当前环境已安装 extra 时验收；否则 skip（默认 CI 无 extra 时不失败）。"""
    spec = importlib.util.find_spec("mcp_agent")
    if spec is None:
        pytest.skip("当前 venv 未安装 mcp-agent extra，跳过 AC-0.5")
    import importlib.metadata as im

    ver = im.version("mcp-agent")
    assert ver == "0.2.6", f"期望 mcp-agent==0.2.6，实际 {ver}"


def test_when_mcp_agent_installed_import_submodules() -> None:
    spec = importlib.util.find_spec("mcp_agent")
    if spec is None:
        pytest.skip("当前 venv 未安装 mcp-agent extra")
    import mcp_agent  # type: ignore[import-untyped]

    assert mcp_agent is not None
